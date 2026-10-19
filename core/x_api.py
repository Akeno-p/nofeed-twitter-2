"""X API v2 との通信。OAuth 2.0 (PKCE) と各エンドポイントの薄いラッパー。"""

import base64
import hashlib
import logging
import secrets
import threading
from datetime import timedelta
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

API_BASE = "https://api.x.com/2"
AUTHORIZE_URL = "https://x.com/i/oauth2/authorize"
TOKEN_URL = "https://api.x.com/2/oauth2/token"
SCOPES = "tweet.read tweet.write users.read offline.access media.write"
TIMEOUT = 30


class XApiError(Exception):
    """画面にそのまま出せる日本語メッセージを持つ。"""

    def __init__(self, message, status=None, needs_reconnect=False):
        super().__init__(message)
        self.message = message
        self.status = status
        self.needs_reconnect = needs_reconnect


def is_configured():
    return bool(settings.X_CLIENT_ID and settings.X_CLIENT_SECRET)


# ---------- OAuth ----------


def new_pkce():
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def build_authorize_url(state, challenge):
    query = urlencode(
        {
            "response_type": "code",
            "client_id": settings.X_CLIENT_ID,
            "redirect_uri": settings.X_REDIRECT_URI,
            "scope": SCOPES,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    return f"{AUTHORIZE_URL}?{query}"


def _token_request(data):
    try:
        resp = requests.post(
            TOKEN_URL,
            data=data,
            auth=(settings.X_CLIENT_ID, settings.X_CLIENT_SECRET),
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        raise XApiError(
            "Xに接続できませんでした。ネットワークを確認してください。"
        ) from exc
    if resp.status_code != 200:
        try:
            body = resp.json()
        except ValueError:
            body = {}
        # 原因をサーバーのログに残す (トークンは含めない)
        logger.warning(
            "X token endpoint returned %s: error=%s description=%s",
            resp.status_code,
            body.get("error"),
            body.get("error_description"),
        )
        raise XApiError(
            "Xとの連携が無効になりました。連携をやり直してください。",
            status=resp.status_code,
            needs_reconnect=True,
        )
    return resp.json()


def exchange_code(code, verifier):
    return _token_request(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.X_REDIRECT_URI,
            "code_verifier": verifier,
        }
    )


def _apply_token(account, token):
    account.access_token = token["access_token"]
    # 更新トークンは使うたびに新しくなる。返ってこなければ古いものを残す。
    account.refresh_token = token.get("refresh_token") or account.refresh_token
    account.expires_at = timezone.now() + timedelta(
        seconds=int(token.get("expires_in", 7200))
    )


# 更新トークンは1回しか使えない。2つの処理が同時に更新すると2つ目が失敗し、
# 連携が取り消されることがある。そのため、更新は1つずつ順番に行う。
_REFRESH_LOCK = threading.Lock()


def refresh(account):
    """アクセストークンを更新する。他の処理がすでに更新していたら、その結果を使う。"""
    with _REFRESH_LOCK:
        latest = type(account).objects.filter(pk=account.pk).first()
        if latest is not None and latest.refresh_token != account.refresh_token:
            # 待っている間に、別の処理が更新を終えていた。もう一度更新せずに、その結果を取り込む。
            account.access_token = latest.access_token
            account.refresh_token = latest.refresh_token
            account.expires_at = latest.expires_at
            return

        if not account.refresh_token:
            raise XApiError(
                "Xの連携の有効期限が切れました。連携をやり直してください。",
                needs_reconnect=True,
            )
        token = _token_request(
            {
                "grant_type": "refresh_token",
                "refresh_token": account.refresh_token,
                "client_id": settings.X_CLIENT_ID,
            }
        )
        _apply_token(account, token)
        account.save(update_fields=["access_token", "refresh_token", "expires_at"])


def apply_new_token(account, token):
    _apply_token(account, token)


# ---------- API ----------


def _error_message(resp):
    status = resp.status_code
    try:
        body = resp.json()
    except ValueError:
        body = {}
    detail = body.get("detail") or body.get("title") or ""
    if status == 401:
        return "Xの認証が無効です。連携をやり直してください。", True
    if status == 402:
        return (
            "Xのクレジットが不足しています。Developer Console でチャージしてください。",
            False,
        )
    if status == 403:
        return f"Xに拒否されました。{detail}".strip(), False
    if status == 429:
        return (
            "Xのリクエスト回数の上限に達しました。しばらく待ってからやり直してください。",
            False,
        )
    return f"Xのエラー ({status}) {detail}".strip(), False


def request(account, method, path, **kwargs):
    """アクセストークンが切れそうなら更新してから API を呼ぶ。"""
    if account.expires_at <= timezone.now() + timedelta(seconds=60):
        refresh(account)

    def send():
        return requests.request(
            method,
            f"{API_BASE}{path}",
            headers={"Authorization": f"Bearer {account.access_token}"},
            timeout=TIMEOUT,
            **kwargs,
        )

    try:
        resp = send()
        if resp.status_code == 401:  # 失効していたら1回だけ更新して再試行
            refresh(account)
            resp = send()
    except requests.RequestException as exc:
        raise XApiError(
            "Xに接続できませんでした。ネットワークを確認してください。"
        ) from exc

    if not resp.ok:
        message, reconnect = _error_message(resp)
        raise XApiError(message, status=resp.status_code, needs_reconnect=reconnect)
    return resp.json()


def get_me(access_token):
    """連携直後 (まだ XAccount が無い段階) に自分の情報を取る。"""
    try:
        resp = requests.get(
            f"{API_BASE}/users/me",
            params={"user.fields": "profile_image_url"},
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        raise XApiError(
            "Xに接続できませんでした。ネットワークを確認してください。"
        ) from exc
    if not resp.ok:
        message, _ = _error_message(resp)
        raise XApiError(message, status=resp.status_code)
    return resp.json()["data"]
