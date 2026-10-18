"""X との同期・投稿のロジック。取得した内容は Post に保存して画面に出す。"""

import re
from decimal import Decimal
from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from . import x_api
from .models import Post

TWEET_PARAMS = {
    "tweet.fields": "created_at,author_id,conversation_id,referenced_tweets,attachments,entities",
    "expansions": "author_id,attachments.media_keys",
    "user.fields": "name,username,profile_image_url",
    "media.fields": "url,preview_image_url,type",
}
MAX_PAGES = 3
PAGE_SIZE = 100  # 1ページあたりの最大取得件数 (X の上限)

# X API の従量課金 (https://docs.x.com/x-api/getting-started/pricing)。単位はドル。料金改定で変わりうる。
# Owned Reads (自分のツイート・自分へのメンションの取得) が安くなるのは、
# Developer Console でアプリを作ったアカウント本人だけ。それ以外のアカウントは通常の読み取り料金になる。
PRICE_OWNED_READ = Decimal("0.001")  # Owned Reads (1件あたり)
PRICE_READ = Decimal("0.005")  # 通常の読み取り (1件あたり)
PRICE_POST_WITH_URL = Decimal("0.20")  # リンク付きの投稿 (1件あたり)
# X が自動でリンクにする書き方 (https://… のほか、example.com のような書き方もリンクになる)。
# 当てはまったら、料金の確認を済ませた投稿だけ通す。取りこぼすと高くつくので、判定は広め
# (Node.js なども当てはまる)。JS も同じ正規表現を使う (大文字・小文字は区別しない)。
LINK_PATTERN = r"https?://|(?<![A-Za-z0-9@#$_./-])(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}(?![A-Za-z0-9-])"
LINK_LIKE = re.compile(LINK_PATTERN, re.IGNORECASE)
LEADING_MENTIONS = re.compile(r"^(?:@\w+(?:\s+|$))+")  # 「@id 本文」「@id」(画像だけの返信) の両方
TRAILING_TCO = re.compile(r"\s*https://t\.co/\w+\s*$")
MEDIA_PAGE = re.compile(r"/(?:photo|video)/\d+$")
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}


class ValidationError(Exception):
    """入力エラー。field はエラーを出す入力欄 ("text" か "images")。"""

    def __init__(self, message, field="text"):
        super().__init__(message)
        self.field = field


def tweet_weight(text):
    """Xの文字数カウント。半角英数は1、日本語などは2 (上限は280)。"""
    weight = 0
    for ch in text:
        cp = ord(ch)
        weight += 1 if (cp <= 4351 or 8192 <= cp <= 8205 or 8208 <= cp <= 8223 or 8242 <= cp <= 8247) else 2
    return weight


def validate_text(text, has_images, link_confirmed=False):
    """link_confirmed は、リンク付きの投稿の料金確認で「OK」を押したかどうか。"""
    text = text.strip()
    if not text and not has_images:
        raise ValidationError("本文を入力してください")
    if len(text) > settings.TWEET_MAX_LENGTH:
        raise ValidationError(f"{settings.TWEET_MAX_LENGTH}文字以内で入力してください")
    if tweet_weight(text) > 280:
        raise ValidationError("文字数がXの上限を超えています")
    if LINK_LIKE.search(text) and not link_confirmed:
        raise ValidationError("リンク付きの投稿は料金が高いため、確認してから投稿してください")
    return text


def validate_images(files):
    if len(files) > settings.TWEET_MAX_IMAGES:
        raise ValidationError(f"画像は{settings.TWEET_MAX_IMAGES}枚までです", field="images")
    for f in files:
        if f.content_type not in ALLOWED_IMAGE_TYPES:
            raise ValidationError("画像は JPEG / PNG / GIF / WebP のみ添付できます", field="images")
        if f.size > settings.TWEET_IMAGE_MAX_BYTES:
            raise ValidationError("画像は1枚あたり5MBまでです", field="images")
    if any(f.content_type == "image/gif" for f in files) and len(files) > 1:
        raise ValidationError("GIFは他の画像と同時に添付できません", field="images")


def _yen(usd):
    """ドルの金額を円にして表示する (例: 0.16円 / 0.8円 / 48円)。為替は設定値で換算した目安。"""
    yen = Decimal(usd) * settings.USD_JPY_RATE
    if yen >= 10:
        return f"{yen.quantize(Decimal('1')):,}円"
    return f"{yen.quantize(Decimal('0.01')).normalize():f}円"


def link_post_price():
    """リンク付きの投稿にかかる料金 (円・目安)。投稿前の確認文に出す。"""
    return _yen(PRICE_POST_WITH_URL)


def sync_unit_price(app_owner=True):
    """取得ボタンの確認画面に出す、1件あたりの料金 (円・目安)。

    ツイートもリプライ (メンション) も Owned Reads で取るので、どちらも同じ金額。
    app_owner=False は、Developer Console でアプリを作ったアカウント以外で取得したときの金額。
    """
    return _yen(PRICE_OWNED_READ if app_owner else PRICE_READ)


# ---------- 保存 ----------


def strip_media_urls(item):
    """本文から、添付画像・動画の短縮URL (https://t.co/...) を取り除く。

    X は、画像を付けたツイートの本文の末尾に、その画像のURLを自動で付けて返す。
    本文に自分で書いたリンクは、そのまま残す。
    """
    text = item["text"]
    media_keys = item.get("attachments", {}).get("media_keys")
    if not media_keys:
        return text
    removed = False
    for url in item.get("entities", {}).get("urls", []):
        # 画像のURLかどうかは、media_key があるか、展開先が画像・動画のページかで判断する
        if url.get("media_key") or MEDIA_PAGE.search(url.get("expanded_url", "")):
            text = text.replace(url["url"], "")
            removed = True
    if not removed:  # entities が無いときは、画像のURLが末尾に1つだけ付く決まりを使う
        text = TRAILING_TCO.sub("", text)
    return re.sub(r"[ \t]+\n", "\n", text).strip()


def _media_urls(post, media_by_key):
    urls = []
    for key in post.get("attachments", {}).get("media_keys", []):
        media = media_by_key.get(key, {})
        url = media.get("url") or media.get("preview_image_url")
        if url:
            urls.append(url)
    return urls


def save_posts(account, payload):
    """API のレスポンス (data / includes) を Post に保存する。保存した件数を返す。"""
    data = payload.get("data") or []
    if isinstance(data, dict):
        data = [data]
    includes = payload.get("includes", {})
    users = {u["id"]: u for u in includes.get("users", [])}
    media_by_key = {m["media_key"]: m for m in includes.get("media", [])}

    count = 0
    for item in data:
        author = users.get(item.get("author_id"), {})
        is_mine = item.get("author_id") == account.x_user_id
        parent = next(
            (r["id"] for r in item.get("referenced_tweets", []) if r["type"] == "replied_to"),
            None,
        )
        text = strip_media_urls(item)
        if parent:
            text = LEADING_MENTIONS.sub("", text)
        Post.objects.update_or_create(
            account=account,
            x_id=item["id"],
            defaults={
                "text": text,
                "posted_at": parse_datetime(item["created_at"]) if "created_at" in item else timezone.now(),
                "author_x_id": item.get("author_id", ""),
                "author_username": author.get("username") or (account.username if is_mine else ""),
                "author_name": author.get("name") or (account.name if is_mine else ""),
                "author_avatar": author.get("profile_image_url") or (account.profile_image_url if is_mine else ""),
                "is_mine": is_mine,
                "in_reply_to_x_id": parent,
                "media_urls": _media_urls(item, media_by_key),
            },
        )
        count += 1
    return count


def _fetch_pages(account, path, params):
    """next_token をたどって最大 MAX_PAGES ページ取得し、そのつど保存する。

    戻り値は、この取得で見えた一番新しい投稿のID (次回の since_id に使う)。
    """
    params = dict(params)
    newest = None
    for page in range(MAX_PAGES):
        payload = x_api.request(account, "GET", path, params=params)
        save_posts(account, payload)
        meta = payload.get("meta", {})
        if page == 0:
            newest = meta.get("newest_id")
        token = meta.get("next_token")
        if not token:
            break
        params["pagination_token"] = token
    return newest


# ---------- 同期 ----------


def sync_own_posts(account):
    """自分のツイートと自分の返信を取得する (前回より新しいものだけ)。"""
    params = {**TWEET_PARAMS, "max_results": 100, "exclude": "retweets"}
    if account.since_own_id:
        params["since_id"] = account.since_own_id
    newest = _fetch_pages(account, f"/users/{account.x_user_id}/tweets", params)
    if newest:
        account.since_own_id = newest
        account.save(update_fields=["since_own_id"])


def sync_replies(account):
    """自分宛ての返信を取得する。先に自分の投稿を同期して、返信先が分かるようにする。

    検索 (1件 $0.005) ではなく、自分へのメンション一覧 (Owned Reads、1件 $0.001) から取る。
    返信の本文には「@自分」が入るので、自分のツイートへの返信はメンション一覧に含まれる。
    新しく見つかった返信の件数を返す。
    """
    sync_own_posts(account)
    params = {**TWEET_PARAMS, "max_results": 100}
    if account.since_reply_id:
        params["since_id"] = account.since_reply_id
    before = Post.objects.filter(account=account, is_mine=False).count()
    newest = _fetch_pages(account, f"/users/{account.x_user_id}/mentions", params)
    if newest:
        account.since_reply_id = newest
        account.save(update_fields=["since_reply_id"])
    _prune_unrelated_replies(account)
    return Post.objects.filter(account=account, is_mine=False).count() - before


def _prune_unrelated_replies(account):
    """自分の投稿への返信でないもの (返信先が手元に無いもの) を消す。"""
    mine = Post.objects.filter(account=account, is_mine=True).values("x_id")
    Post.objects.filter(account=account, is_mine=False).exclude(in_reply_to_x_id__in=mine).delete()


# ---------- 投稿 ----------


def _upload_image(account, f):
    payload = x_api.request(
        account,
        "POST",
        "/media/upload",
        files={"media": (f.name, f.read(), f.content_type)},
        data={"media_category": "tweet_gif" if f.content_type == "image/gif" else "tweet_image"},
    )
    return payload["data"]["id"]


def post_tweet(account, text, images=(), reply_to=None):
    """投稿して、結果を Post に保存する。"""
    media_ids = [_upload_image(account, f) for f in images]
    body = {"text": text}
    if media_ids:
        body["media"] = {"media_ids": media_ids}
    if reply_to:
        body["reply"] = {"in_reply_to_tweet_id": reply_to}
    created = x_api.request(account, "POST", "/tweets", json=body)["data"]

    if media_ids:
        # 作成のレスポンスには画像のURLが入っていないので、取り直して保存する
        payload = x_api.request(account, "GET", f"/tweets/{created['id']}", params=TWEET_PARAMS)
        save_posts(account, payload)
    else:
        save_posts(
            account,
            {
                "data": [
                    {
                        "id": created["id"],
                        "text": created.get("text", text),
                        "author_id": account.x_user_id,
                        "created_at": timezone.now().isoformat(),
                        "referenced_tweets": [{"type": "replied_to", "id": reply_to}] if reply_to else [],
                    }
                ]
            },
        )
    return Post.objects.get(account=account, x_id=created["id"])
