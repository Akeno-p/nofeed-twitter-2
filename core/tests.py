import re
from datetime import timedelta
from unittest import mock

import pyotp
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import TotpDevice

from . import services, x_api
from .models import Post, XAccount

ME = "100"


def fake_response(status=200, body=None):
    resp = mock.Mock()
    resp.status_code = status
    resp.ok = status < 400
    resp.json.return_value = body if body is not None else {}
    return resp


def make_account(user_id=ME, username="me", active=True, **kw):
    return XAccount.objects.create(
        x_user_id=user_id,
        username=username,
        name=f"Name {username}",
        access_token="tok",
        refresh_token="ref",
        expires_at=timezone.now() + timedelta(hours=1),
        is_active=active,
        **kw,
    )


def without_scripts(html):
    """画面の HTML から <script> を除く (JS のコードやコメントを、画面の文言として数えないため)。"""
    return re.sub(r"<script>.*?</script>", "", html, flags=re.DOTALL)


class LoggedInTestCase(TestCase):
    def setUp(self):
        cache.clear()
        user = get_user_model().objects.create_user("owner", password="pw-correct-1")
        TotpDevice.objects.create(user=user, secret=pyotp.random_base32(), confirmed=True)
        self.client.force_login(user)
        session = self.client.session
        session["two_factor_verified"] = True
        session.save()


TWEETS_PAYLOAD = {
    "data": [
        {  # 自分のツイート (画像付き)
            "id": "11", "text": "池袋です", "author_id": ME, "created_at": "2026-09-04T01:00:00.000Z",
            "attachments": {"media_keys": ["m1"]},
        },
        {  # 自分の返信 (相手の返信 22 への返事)
            "id": "33", "text": "@sub ありがとう", "author_id": ME, "created_at": "2026-09-29T03:00:00.000Z",
            "referenced_tweets": [{"type": "replied_to", "id": "22"}],
        },
        {  # 他人のツイートへの返信 (どの画面にも出さない)
            "id": "44", "text": "@stranger こんにちは", "author_id": ME, "created_at": "2026-09-30T03:00:00.000Z",
            "referenced_tweets": [{"type": "replied_to", "id": "999"}],
        },
    ],
    "includes": {
        "users": [{"id": ME, "username": "me", "name": "Name me", "profile_image_url": "https://x/me.jpg"}],
        "media": [{"media_key": "m1", "type": "photo", "url": "https://pbs/1.jpg"}],
    },
    "meta": {"newest_id": "44", "result_count": 3},
}

REPLIES_PAYLOAD = {
    "data": [
        {
            "id": "22", "text": "@me いい", "author_id": "200", "created_at": "2026-09-29T02:00:00.000Z",
            "referenced_tweets": [{"type": "replied_to", "id": "11"}],
        },
        {  # 自分とは無関係の返信は捨てられる
            "id": "55", "text": "@me ??", "author_id": "300", "created_at": "2026-09-30T02:00:00.000Z",
            "referenced_tweets": [{"type": "replied_to", "id": "888"}],
        },
    ],
    "includes": {"users": [
        {"id": "200", "username": "sub", "name": "サブ"},
        {"id": "300", "username": "other", "name": "Other"},
    ]},
    "meta": {"newest_id": "55", "result_count": 2},
}


class SyncTests(LoggedInTestCase):
    def setUp(self):
        super().setUp()
        self.account = make_account()

    @mock.patch("core.x_api.requests.request")
    def test_sync_stores_posts_and_remembers_cursor(self, req):
        req.return_value = fake_response(body=TWEETS_PAYLOAD)
        services.sync_own_posts(self.account)

        self.assertEqual(Post.objects.count(), 3)
        tweet = Post.objects.get(x_id="11")
        self.assertEqual(tweet.media_urls, ["https://pbs/1.jpg"])
        self.assertTrue(tweet.is_mine)
        # 返信先のメンションは表示用に取り除く
        self.assertEqual(Post.objects.get(x_id="33").text, "ありがとう")
        self.account.refresh_from_db()
        self.assertEqual(self.account.since_own_id, "44")

        # 2回目は since_id 付きで、新しい分だけ取りに行く
        req.return_value = fake_response(body={"meta": {"result_count": 0}})
        services.sync_own_posts(self.account)
        params = req.call_args.kwargs["params"]
        self.assertEqual(params["since_id"], "44")
        self.assertEqual(params["exclude"], "retweets")
        self.assertTrue(req.call_args.args[1].endswith("/users/100/tweets"))

    @mock.patch("core.x_api.requests.request")
    def test_tweets_page_lists_only_own_toplevel_tweets(self, req):
        req.return_value = fake_response(body=TWEETS_PAYLOAD)
        resp = self.client.post(reverse("core:sync_tweets"), headers={"x-requested-with": "XMLHttpRequest"})
        self.assertEqual(resp.status_code, 200)
        html = resp.json()["html"]
        self.assertIn("池袋です", html)
        self.assertIn("https://pbs/1.jpg", html)
        self.assertNotIn("こんにちは", html)  # 他人への返信は載せない
        self.assertNotIn("ありがとう", html)  # 返信はリプライ画面側

    @mock.patch("core.x_api.requests.request")
    def test_replies_are_grouped_and_unrelated_dropped(self, req):
        req.side_effect = [fake_response(body=TWEETS_PAYLOAD), fake_response(body=REPLIES_PAYLOAD)]
        resp = self.client.post(reverse("core:sync_replies"), headers={"x-requested-with": "XMLHttpRequest"})
        body = resp.json()
        self.assertEqual(body["found"], 1)
        self.assertIn("あなたのツイート", body["html"])
        self.assertIn("池袋です", body["html"])  # 親ツイートの引用
        self.assertIn("いい", body["html"])
        self.assertIn("ありがとう", body["html"])  # 自分の返事がぶら下がる
        self.assertFalse(Post.objects.filter(x_id="55").exists())
        # 検索 ($0.005/件) ではなく、自分へのメンション一覧 (Owned Reads、$0.001/件) から取る
        mentions_call = req.call_args_list[1]
        self.assertTrue(mentions_call.args[1].endswith("/users/100/mentions"))
        self.assertNotIn("query", mentions_call.kwargs["params"])

    @mock.patch("core.x_api.requests.request")
    def test_replies_sync_remembers_cursor(self, req):
        req.side_effect = [fake_response(body=TWEETS_PAYLOAD), fake_response(body=REPLIES_PAYLOAD)]
        services.sync_replies(self.account)
        self.account.refresh_from_db()
        self.assertEqual(self.account.since_reply_id, "55")

        req.side_effect = [fake_response(body={"meta": {}}), fake_response(body={"meta": {}})]
        services.sync_replies(self.account)
        self.assertEqual(req.call_args_list[-1].kwargs["params"]["since_id"], "55")

    @mock.patch("core.x_api.requests.request")
    def test_api_errors_are_shown_in_japanese(self, req):
        for status, needle in [(402, "クレジット"), (429, "上限"), (401, "連携")]:
            req.return_value = fake_response(status=status, body={"detail": "d"})
            resp = self.client.post(reverse("core:sync_tweets"), headers={"x-requested-with": "XMLHttpRequest"})
            self.assertEqual(resp.status_code, 502)
            self.assertIn(needle, resp.json()["error"])

    @mock.patch("core.x_api.requests.request")
    def test_expired_token_is_refreshed_first(self, req):
        self.account.expires_at = timezone.now() - timedelta(minutes=1)
        self.account.save()
        req.return_value = fake_response(body={"meta": {}})
        with mock.patch("core.x_api.requests.post") as post:
            post.return_value = fake_response(
                body={"access_token": "new", "refresh_token": "ref2", "expires_in": 7200}
            )
            services.sync_own_posts(self.account)
        self.account.refresh_from_db()
        self.assertEqual(self.account.access_token, "new")
        self.assertEqual(self.account.refresh_token, "ref2")
        self.assertEqual(req.call_args.kwargs["headers"]["Authorization"], "Bearer new")
        self.assertEqual(post.call_args.kwargs["data"]["grant_type"], "refresh_token")


class PostingTests(LoggedInTestCase):
    def setUp(self):
        super().setUp()
        self.account = make_account()

    def post(self, data, **kw):
        return self.client.post(
            reverse("core:create_tweet"), data, headers={"x-requested-with": "XMLHttpRequest"}, **kw
        )

    @mock.patch("core.x_api.requests.request")
    def test_text_tweet(self, req):
        req.return_value = fake_response(201, {"data": {"id": "77", "text": "こんにちは"}})
        resp = self.post({"text": "こんにちは"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("こんにちは", resp.json()["html"])
        self.assertEqual(req.call_args.kwargs["json"], {"text": "こんにちは"})
        self.assertTrue(Post.objects.get(x_id="77").is_mine)

    @mock.patch("core.x_api.requests.request")
    def test_tweet_with_image_uploads_first(self, req):
        req.side_effect = [
            fake_response(200, {"data": {"id": "mid"}}),
            fake_response(201, {"data": {"id": "78", "text": "写真"}}),
            fake_response(200, {
                "data": {"id": "78", "text": "写真", "author_id": ME, "created_at": "2026-10-17T00:00:00Z",
                         "attachments": {"media_keys": ["k"]}},
                "includes": {"media": [{"media_key": "k", "type": "photo", "url": "https://pbs/x.jpg"}]},
            }),
        ]
        img = SimpleUploadedFile("a.png", b"\x89PNG....", content_type="image/png")
        resp = self.post({"text": "写真", "images": img})
        self.assertEqual(resp.status_code, 200, resp.content)
        upload, create, _fetch = req.call_args_list
        self.assertTrue(upload.args[1].endswith("/media/upload"))
        self.assertEqual(upload.kwargs["data"]["media_category"], "tweet_image")
        self.assertEqual(create.kwargs["json"]["media"], {"media_ids": ["mid"]})
        self.assertEqual(Post.objects.get(x_id="78").media_urls, ["https://pbs/x.jpg"])

    @mock.patch("core.x_api.requests.request")
    def test_validation(self, req):
        self.assertEqual(self.post({"text": "  "}).status_code, 400)
        self.assertEqual(self.post({"text": "あ" * 141}).status_code, 400)
        bad = SimpleUploadedFile("a.pdf", b"x", content_type="application/pdf")
        self.assertEqual(self.post({"text": "x", "images": bad}).status_code, 400)
        big = SimpleUploadedFile("a.png", b"x" * (5 * 1024 * 1024 + 1), content_type="image/png")
        self.assertEqual(self.post({"text": "x", "images": big}).status_code, 400)
        five = [SimpleUploadedFile(f"{i}.png", b"x", content_type="image/png") for i in range(5)]
        self.assertEqual(self.post({"text": "x", "images": five}).status_code, 400)
        req.assert_not_called()  # 入力が不正なら X には何も送らない

    @mock.patch("core.x_api.requests.request")
    def test_validation_errors_name_the_field(self, req):
        body = self.post({"text": "  "}).json()
        self.assertEqual((body["field"], body["error"]), ("text", "本文を入力してください"))
        big = SimpleUploadedFile("a.png", b"x" * (5 * 1024 * 1024 + 1), content_type="image/png")
        self.assertEqual(self.post({"text": "x", "images": big}).json()["field"], "images")

    @mock.patch("core.x_api.requests.request")
    def test_x_errors_have_no_field_so_they_use_the_banner(self, req):
        req.return_value = fake_response(402, {})
        self.assertNotIn("field", self.post({"text": "x"}).json())

    def test_140_japanese_chars_fit_xs_280_weight(self):
        self.assertEqual(services.validate_text("あ" * 140, False), "あ" * 140)
        self.assertEqual(services.tweet_weight("abc"), 3)

    @mock.patch("core.x_api.requests.request")
    def test_reply_only_to_replies_on_my_tweets(self, req):
        Post.objects.create(account=self.account, x_id="11", text="t", posted_at=timezone.now(),
                            author_x_id=ME, author_username="me", author_name="me", is_mine=True)
        Post.objects.create(account=self.account, x_id="22", text="r", posted_at=timezone.now(),
                            author_x_id="2", author_username="sub", author_name="s", is_mine=False,
                            in_reply_to_x_id="11")
        req.return_value = fake_response(201, {"data": {"id": "99", "text": "どうも"}})
        resp = self.client.post(reverse("core:create_reply"), {"reply_to": "22", "text": "どうも"},
                                headers={"x-requested-with": "XMLHttpRequest"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(req.call_args.kwargs["json"]["reply"], {"in_reply_to_tweet_id": "22"})
        self.assertIn("どうも", resp.json()["html"])

        resp = self.client.post(reverse("core:create_reply"), {"reply_to": "12345", "text": "x"},
                                headers={"x-requested-with": "XMLHttpRequest"})
        self.assertEqual(resp.status_code, 404)

    def test_requires_connected_account(self):
        XAccount.objects.all().delete()
        self.assertEqual(self.post({"text": "x"}).status_code, 400)

    def test_get_not_allowed(self):
        self.assertEqual(self.client.get(reverse("core:create_tweet")).status_code, 405)


@override_settings(X_CLIENT_ID="cid", X_CLIENT_SECRET="sec", X_REDIRECT_URI="http://127.0.0.1:8000/x/callback/")
class ConnectTests(LoggedInTestCase):
    def setUp(self):
        super().setUp()
        self.client.defaults["HTTP_HOST"] = "127.0.0.1:8000"  # 登録したリダイレクトURIと同じアドレス

    def test_connect_from_wrong_host_is_stopped_with_guidance(self):
        self.client.defaults["HTTP_HOST"] = "localhost:8000"
        resp = self.client.get(reverse("core:x_connect"))
        self.assertRedirects(resp, reverse("core:tweets"), fetch_redirect_response=False)
        self.assertNotIn("x_oauth", self.client.session)  # Xへは進まない
        page = self.client.get(reverse("core:tweets"))
        self.assertContains(page, "http://127.0.0.1:8000/")
        self.assertContains(page, "localhost:8000")

    def test_callback_without_pending_connect_explains_and_logs(self):
        with self.assertLogs("core.views", "WARNING") as logs:
            resp = self.client.get(reverse("core:x_callback"), {"code": "c", "state": "s"})
        self.assertRedirects(resp, reverse("core:tweets"), fetch_redirect_response=False)
        self.assertIn("no pending connect", logs.output[0])
        self.assertContains(self.client.get(reverse("core:tweets")), "連携の開始記録が見つかりませんでした")

    def test_callback_state_mismatch_has_its_own_message(self):
        self.client.get(reverse("core:x_connect"))
        with self.assertLogs("core.views", "WARNING") as logs:
            self.client.get(reverse("core:x_callback"), {"code": "c", "state": "forged"})
        self.assertIn("state mismatch", logs.output[0])
        self.assertContains(self.client.get(reverse("core:tweets")), "別の連携操作と混ざりました")

    def test_connect_redirects_with_pkce(self):
        resp = self.client.get(reverse("core:x_connect"))
        self.assertEqual(resp.status_code, 302)
        url = resp["Location"]
        self.assertTrue(url.startswith("https://x.com/i/oauth2/authorize?"))
        for part in ("client_id=cid", "code_challenge_method=S256", "response_type=code",
                     "offline.access", "media.write", "tweet.write"):
            self.assertIn(part, url)
        self.assertIn("state", self.client.session["x_oauth"])

    def test_pkce_challenge_matches_verifier(self):
        import base64
        import hashlib
        verifier, challenge = x_api.new_pkce()
        expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        self.assertEqual(challenge, expected)

    def test_callback_rejects_wrong_state(self):
        self.client.get(reverse("core:x_connect"))
        resp = self.client.get(reverse("core:x_callback"), {"code": "c", "state": "forged"})
        self.assertRedirects(resp, reverse("core:tweets"), fetch_redirect_response=False)
        self.assertEqual(XAccount.objects.count(), 0)

    @mock.patch("core.x_api.requests.get")
    @mock.patch("core.x_api.requests.post")
    def test_callback_creates_account_and_activates(self, post, get):
        post.return_value = fake_response(body={"access_token": "A", "refresh_token": "R", "expires_in": 7200})
        get.return_value = fake_response(body={"data": {"id": "500", "username": "newone", "name": "New",
                                                        "profile_image_url": "https://x/n.jpg"}})
        old = make_account()
        self.client.get(reverse("core:x_connect"))
        state = self.client.session["x_oauth"]["state"]
        resp = self.client.get(reverse("core:x_callback"), {"code": "abc", "state": state})
        self.assertRedirects(resp, reverse("core:tweets"), fetch_redirect_response=False)

        acc = XAccount.objects.get(x_user_id="500")
        self.assertTrue(acc.is_active)
        old.refresh_from_db()
        self.assertFalse(old.is_active)
        sent = post.call_args.kwargs
        self.assertEqual(sent["data"]["grant_type"], "authorization_code")
        self.assertEqual(sent["auth"], ("cid", "sec"))
        self.assertTrue(sent["data"]["code_verifier"])

    def test_switch_and_disconnect(self):
        a = make_account("1", "a", active=True)
        b = make_account("2", "b", active=False)
        self.client.post(reverse("core:x_switch", args=[b.pk]))
        a.refresh_from_db(); b.refresh_from_db()
        self.assertFalse(a.is_active)
        self.assertTrue(b.is_active)

        Post.objects.create(account=b, x_id="1", text="t", posted_at=timezone.now(), author_x_id="2",
                            author_username="b", author_name="b", is_mine=True)
        self.client.post(reverse("core:x_disconnect", args=[b.pk]))
        self.assertFalse(XAccount.objects.filter(pk=b.pk).exists())
        self.assertEqual(Post.objects.count(), 0)
        a.refresh_from_db()
        self.assertTrue(a.is_active)  # 残りのアカウントが自動で使用中になる

    def test_settings_menu_and_pages_render(self):
        make_account("1", "alice")
        html = self.client.get(reverse("core:tweets")).content.decode()
        self.assertIn("@alice", html)
        self.assertIn("ログアウト", html)
        self.assertIn("Xアカウントを追加", html)
        self.assertContains(self.client.get(reverse("core:replies")), "リプライ取得")

    def test_pages_without_account_show_connect_prompt(self):
        self.assertContains(self.client.get(reverse("core:tweets")), "Xアカウントを連携")


class DevPreviewTests(LoggedInTestCase):
    """デザイン確認用ページ: DEBUG のときだけ開け、本物の認証情報は使わない。"""

    PATHS = ["/dev/", "/dev/two-factor-setup/", "/dev/x-connect/"]

    def test_closed_when_debug_is_off(self):
        for path in self.PATHS:
            self.assertEqual(self.client.get(path).status_code, 404, path)

    def test_requires_login_even_in_debug(self):
        self.client.logout()
        with override_settings(DEBUG=True):
            for path in self.PATHS:
                self.assertRedirects(
                    self.client.get(path), reverse("accounts:login"), fetch_redirect_response=False
                )

    @override_settings(DEBUG=True)
    def test_two_factor_setup_preview_shows_qr_even_when_already_registered(self):
        resp = self.client.get("/dev/two-factor-setup/")
        self.assertContains(resp, "2段階認証 設定")
        self.assertContains(resp, "<svg")

    @override_settings(DEBUG=True)
    def test_preview_does_not_touch_or_reveal_the_real_secret(self):
        from accounts.models import TotpDevice

        device = TotpDevice.objects.get()
        before = (device.secret, device.confirmed, TotpDevice.objects.count())
        html = self.client.get("/dev/two-factor-setup/").content.decode()
        device.refresh_from_db()
        self.assertEqual(before, (device.secret, device.confirmed, TotpDevice.objects.count()))
        self.assertNotIn(device.secret, html)
        # 実際の2段階認証の状態も変わっていない (画面を開いても、認証済みのまま)
        self.assertTrue(self.client.session["two_factor_verified"])

    @override_settings(DEBUG=True)
    def test_two_factor_setup_preview_error_states(self):
        for key, text in [("invalid", "正しくありません"), ("empty", "空欄です"), ("locked", "お待ちください")]:
            resp = self.client.get(f"/dev/two-factor-setup/?error={key}")
            self.assertContains(resp, text)
        self.assertContains(self.client.get("/dev/two-factor-setup/?error=invalid"), 'aria-invalid="true"')
        self.assertNotContains(self.client.get("/dev/two-factor-setup/?error=locked"), 'aria-invalid="true"')

    @override_settings(DEBUG=True, X_CLIENT_ID="cid", X_CLIENT_SECRET="sec")
    def test_x_connect_preview_shows_unconnected_state_even_when_connected(self):
        make_account("1", "alice")  # 連携済みでも
        resp = self.client.get("/dev/x-connect/")
        self.assertContains(resp, "Xアカウントを連携してください")
        self.assertContains(resp, "Xアカウントを連携する")
        self.assertNotContains(resp, "@alice")
        self.assertEqual(XAccount.objects.count(), 1)  # 実際の連携には触れない

    @override_settings(DEBUG=True, X_CLIENT_ID="cid", X_CLIENT_SECRET="sec")
    def test_x_connect_preview_variants(self):
        self.assertContains(self.client.get("/dev/x-connect/?flash=1"), "連携に失敗しました")
        self.assertContains(self.client.get("/dev/x-connect/?configured=0"), "X_CLIENT_ID")

    @override_settings(DEBUG=True)
    def test_index_lists_the_pages(self):
        resp = self.client.get("/dev/")
        for path in self.PATHS[1:]:
            self.assertContains(resp, path)


class RefreshConcurrencyTests(LoggedInTestCase):
    """更新トークンは1回しか使えないので、同時に更新しようとしても1回だけにする。"""

    def setUp(self):
        super().setUp()
        self.account = make_account()

    @mock.patch("core.x_api.requests.post")
    def test_skips_refresh_when_another_request_already_did(self, post):
        stale = XAccount.objects.get(pk=self.account.pk)  # 古い値を持つ処理
        # 別の処理が先に更新を終えた状態を作る
        self.account.access_token = "NEW"
        self.account.refresh_token = "ref-NEW"
        self.account.save()

        x_api.refresh(stale)

        post.assert_not_called()  # 古い更新トークンで、もう一度更新しにいかない
        self.assertEqual((stale.access_token, stale.refresh_token), ("NEW", "ref-NEW"))

    @mock.patch("core.x_api.requests.post")
    def test_refresh_saves_rotated_tokens(self, post):
        post.return_value = fake_response(body={"access_token": "A2", "refresh_token": "R2", "expires_in": 7200})
        x_api.refresh(self.account)
        stored = XAccount.objects.get(pk=self.account.pk)
        self.assertEqual((stored.access_token, stored.refresh_token), ("A2", "R2"))

    @mock.patch("core.x_api.requests.post")
    def test_revoked_refresh_token_asks_to_reconnect_and_logs_reason(self, post):
        post.return_value = fake_response(
            400, {"error": "invalid_request", "error_description": "Value passed for the token was invalid."}
        )
        with self.assertLogs("core.x_api", "WARNING") as logs:
            with self.assertRaises(x_api.XApiError) as ctx:
                x_api.refresh(self.account)
        self.assertTrue(ctx.exception.needs_reconnect)
        self.assertIn("invalid_request", logs.output[0])
        self.assertNotIn("ref", logs.output[0].replace("refresh", ""))  # トークンの値はログに出さない


class SyncConfirmTests(LoggedInTestCase):
    def setUp(self):
        super().setUp()
        make_account()

    def test_tweets_confirm_is_minimal(self):
        html = self.client.get(reverse("core:tweets")).content.decode()
        self.assertIn('id="sync-confirm-dialog"', html)
        self.assertIn("新しいツイートを取得しますか？", html)
        self.assertIn("1件あたり約0.16円かかります。", html)
        self.assertIn("data-sync-confirm", html)

    def test_replies_confirm_shows_owned_read_price(self):
        html = self.client.get(reverse("core:replies")).content.decode()
        self.assertIn("新しいリプライを取得しますか？", html)
        self.assertIn("1件あたり約0.16円かかります。", html)

    def test_non_owner_price_is_noted_only_with_multiple_accounts(self):
        for name in ("core:tweets", "core:replies"):
            self.assertNotContains(self.client.get(reverse(name)), "アプリを作ったアカウント以外")
        make_account(user_id="200", username="sub", active=False)
        for name in ("core:tweets", "core:replies"):
            self.assertContains(self.client.get(reverse(name)), "アプリを作ったアカウント以外は約0.8円です。")

    def test_no_cancel_button_and_no_extra_notes(self):
        for name in ("core:tweets", "core:replies"):
            html = without_scripts(self.client.get(reverse(name)).content.decode())
            self.assertNotIn("data-sync-cancel", html)
            self.assertNotIn("キャンセル", html)
            self.assertNotIn("最大", html)
            self.assertNotIn("目安です", html)
            self.assertNotIn("従量課金", html)
            self.assertNotIn("$", html.split('id="sync-confirm-dialog"')[1].split("</dialog>")[0])

    def test_unit_price_in_yen(self):
        self.assertEqual(services.sync_unit_price(), "0.16円")
        self.assertEqual(services.sync_unit_price(app_owner=False), "0.8円")

    @override_settings(USD_JPY_RATE=__import__("decimal").Decimal("150"))
    def test_rate_comes_from_settings(self):
        self.assertEqual(services.sync_unit_price(), "0.15円")
        self.assertContains(self.client.get(reverse("core:tweets")), "約0.15円")

    def test_page_load_does_not_call_x(self):
        with mock.patch("core.x_api.requests.request") as req:
            self.client.get(reverse("core:tweets"))
            self.client.get(reverse("core:replies"))
        req.assert_not_called()


class ToastTests(LoggedInTestCase):
    def test_toast_area_is_on_main_pages_but_not_on_login(self):
        make_account()
        for name in ("core:tweets", "core:replies"):
            html = self.client.get(reverse(name)).content.decode()
            self.assertIn('id="toast"', html)
            self.assertIn('role="status"', html)
        self.client.logout()
        self.assertNotContains(self.client.get(reverse("accounts:login")), 'id="toast"')


class TimeLabelTests(TestCase):
    def setUp(self):
        from datetime import datetime
        from datetime import timezone as tz

        self.tz = tz
        self.now = datetime(2026, 10, 18, 12, 0, 0, tzinfo=tz.utc)  # 日本時間 21:00

    def label(self, **ago):
        from core.templatetags.core_tags import time_label

        return time_label(self.now - timedelta(**ago), self.now)

    def test_under_a_minute_is_now(self):
        self.assertEqual(self.label(seconds=0), "今")
        self.assertEqual(self.label(seconds=59), "今")

    def test_future_clock_skew_is_now(self):
        self.assertEqual(self.label(seconds=-30), "今")

    def test_minutes(self):
        self.assertEqual(self.label(seconds=60), "1分")
        self.assertEqual(self.label(minutes=20), "20分")
        self.assertEqual(self.label(minutes=59, seconds=59), "59分")

    def test_hours(self):
        self.assertEqual(self.label(hours=1), "1時間")
        self.assertEqual(self.label(hours=5, minutes=40), "5時間")
        self.assertEqual(self.label(hours=23, minutes=59, seconds=59), "23時間")

    def test_a_day_or_more_shows_the_date_without_year(self):
        self.assertEqual(self.label(hours=24), "10月17日")
        self.assertEqual(self.label(days=19), "9月29日")

    def test_a_year_or_more_shows_the_year(self):
        self.assertEqual(self.label(days=366), "2025年10月17日")
        # ちょうど1年前は、まだ年を付けない。それより古いと付く
        from core.templatetags.core_tags import absolute_label

        self.assertEqual(absolute_label(self.now.replace(year=2025), self.now), "10月18日")
        self.assertEqual(absolute_label(self.now.replace(year=2025) - timedelta(seconds=1), self.now), "2025年10月18日")

    def test_last_year_but_under_a_year_has_no_year(self):
        # 去年の12月でも、1年経っていなければ年は付けない
        from datetime import datetime

        v = datetime(2025, 12, 3, 0, 0, tzinfo=self.tz.utc)
        from core.templatetags.core_tags import absolute_label

        self.assertEqual(absolute_label(v, self.now), "12月3日")

    def test_leap_day_does_not_crash(self):
        from datetime import datetime

        from core.templatetags.core_tags import absolute_label

        now = datetime(2028, 2, 29, 12, 0, tzinfo=self.tz.utc)
        # 2028年2月29日の1年前 = 2027年2月28日 (存在しない日付でも落ちない)
        self.assertEqual(absolute_label(datetime(2027, 3, 1, tzinfo=self.tz.utc), now), "3月1日")
        self.assertEqual(absolute_label(datetime(2027, 2, 27, tzinfo=self.tz.utc), now), "2027年2月27日")
        self.assertEqual(absolute_label(datetime(2025, 8, 1, tzinfo=self.tz.utc), now), "2025年8月1日")

    def test_pages_render_time_element_with_fallback_date(self):
        user = get_user_model().objects.create_user("t", password="pw-correct-1")
        TotpDevice.objects.create(user=user, secret=pyotp.random_base32(), confirmed=True)
        self.client.force_login(user)
        s = self.client.session
        s["two_factor_verified"] = True
        s.save()
        acc = make_account()
        Post.objects.create(account=acc, x_id="1", text="t", posted_at=timezone.now() - timedelta(minutes=20),
                            author_x_id=ME, author_username="me", author_name="me", is_mine=True)
        html = self.client.get(reverse("core:tweets")).content.decode()
        self.assertIn('class="js-reltime"', html)
        self.assertIn("20分", html)
        self.assertIn("data-abs=", html)


class MediaUrlStripTests(LoggedInTestCase):
    """画像付きツイートの本文に出る、画像の短縮URLを取り除く。"""

    def setUp(self):
        super().setUp()
        self.account = make_account()

    def save(self, item, media=True):
        item = {"author_id": ME, "created_at": "2026-10-18T00:00:00.000Z", **item}
        if media:
            item["attachments"] = {"media_keys": ["m1"]}
        services.save_posts(self.account, {
            "data": [item],
            "includes": {"media": [{"media_key": "m1", "type": "photo", "url": "https://pbs/1.jpg"}]},
        })
        return Post.objects.get(x_id=item["id"])

    def test_media_url_is_removed_using_entities(self):
        post = self.save({
            "id": "1", "text": "池袋です https://t.co/zPIrGMK4CA",
            "entities": {"urls": [{"url": "https://t.co/zPIrGMK4CA", "media_key": "m1",
                                    "expanded_url": "https://x.com/me/status/1/photo/1"}]},
        })
        self.assertEqual(post.text, "池袋です")
        self.assertEqual(post.media_urls, ["https://pbs/1.jpg"])  # 画像そのものは残る

    def test_url_the_user_wrote_is_kept(self):
        post = self.save({
            "id": "2", "text": "見て https://t.co/REAL12345 すごい https://t.co/MEDIA6789",
            "entities": {"urls": [
                {"url": "https://t.co/REAL12345", "expanded_url": "https://example.com/page"},
                {"url": "https://t.co/MEDIA6789", "media_key": "m1", "expanded_url": "https://x.com/me/status/2/photo/1"},
            ]},
        })
        self.assertEqual(post.text, "見て https://t.co/REAL12345 すごい")

    def test_falls_back_to_trailing_url_without_entities(self):
        post = self.save({"id": "3", "text": "海です https://t.co/i23JxYFOoi"})
        self.assertEqual(post.text, "海です")

    def test_image_only_tweet_has_empty_text(self):
        post = self.save({"id": "4", "text": "https://t.co/dGXckAEyYF"})
        self.assertEqual(post.text, "")

    def test_multiline_text_is_kept(self):
        post = self.save({"id": "5", "text": "一行目\n二行目 https://t.co/AAAAAAAAAA"})
        self.assertEqual(post.text, "一行目\n二行目")

    def test_tweet_without_media_is_never_touched(self):
        post = self.save({"id": "6", "text": "リンク https://t.co/REAL12345"}, media=False)
        self.assertEqual(post.text, "リンク https://t.co/REAL12345")

    def test_reply_with_image_loses_mention_and_url(self):
        post = self.save({
            "id": "7", "text": "@sub 見て https://t.co/MEDIA6789",
            "referenced_tweets": [{"type": "replied_to", "id": "999"}],
        })
        self.assertEqual(post.text, "見て")

    def test_requests_entities_from_x(self):
        self.assertIn("entities", services.TWEET_PARAMS["tweet.fields"])

    def test_image_only_tweet_renders_without_empty_paragraph(self):
        self.save({"id": "8", "text": "https://t.co/dGXckAEyYF"})
        html = self.client.get(reverse("core:tweets")).content.decode()
        self.assertNotIn("t.co", html)
        self.assertIn("https://pbs/1.jpg", html)

    def test_cleanup_migration_function(self):
        import importlib

        mod = importlib.import_module("core.migrations.0002_strip_media_urls_from_saved_posts")
        self.assertEqual(mod.strip_text("池袋です https://t.co/zPIrGMK4CA"), "池袋です")
        self.assertEqual(mod.strip_text("https://t.co/dGXckAEyYF"), "")
        self.assertEqual(mod.strip_text("URLなし"), "URLなし")


class LightboxTests(LoggedInTestCase):
    def setUp(self):
        super().setUp()
        self.account = make_account()

    def add_post(self, x_id, urls):
        Post.objects.create(account=self.account, x_id=x_id, text="t", posted_at=timezone.now(),
                            author_x_id=ME, author_username="me", author_name="me", is_mine=True, media_urls=urls)

    def test_images_are_zoomable_buttons(self):
        self.add_post("1", ["https://pbs/a.jpg", "https://pbs/b.jpg"])
        html = without_scripts(self.client.get(reverse("core:tweets")).content.decode())
        self.assertEqual(html.count("js-zoom"), 2)
        self.assertIn("画像 1 を拡大", html)
        self.assertIn("画像 2 を拡大", html)
        self.assertIn('class="js-gallery', html)

    def test_lightbox_markup_is_on_main_pages_only(self):
        for name in ("core:tweets", "core:replies"):
            html = self.client.get(reverse(name)).content.decode()
            self.assertIn('id="lightbox"', html)
            self.assertIn("data-lightbox-close", html)
        self.client.logout()
        self.assertNotContains(self.client.get(reverse("accounts:login")), 'id="lightbox"')

    def test_replies_page_images_are_zoomable_too(self):
        mine = Post.objects.create(account=self.account, x_id="1", text="t", posted_at=timezone.now(),
                                   author_x_id=ME, author_username="me", author_name="me", is_mine=True)
        Post.objects.create(account=self.account, x_id="2", text="r", posted_at=timezone.now(), author_x_id="2",
                            author_username="sub", author_name="s", is_mine=False, in_reply_to_x_id=mine.x_id,
                            media_urls=["https://pbs/r.jpg"])
        self.assertContains(self.client.get(reverse("core:replies")), "js-zoom")


class ComposeLayoutTests(LoggedInTestCase):
    def test_previews_sit_inside_the_bordered_box_above_the_underline(self):
        make_account()
        html = self.client.get(reverse("core:tweets")).content.decode()
        box = html.index("js-compose-box")
        textarea = html.index('name="text"', box)
        previews = html.index("js-previews", box)
        counter = html.index("js-count", box)
        self.assertLess(box, textarea)
        self.assertLess(textarea, previews)  # 本文欄の下に、プレビュー
        self.assertLess(previews, counter)  # その下に、ボタンの行
        # 下線 (ボーダー) は外側の枠だけが持つ (本文欄自身にはもう無い)
        textarea_tag = html[html.rindex("<textarea", 0, textarea):html.index("</textarea>", textarea)]
        self.assertNotIn("border-b", textarea_tag)
        self.assertIn("border-b", html[box - 20:box + 200])

    def test_add_image_button_is_marked_so_it_can_be_disabled(self):
        make_account()
        self.assertContains(self.client.get(reverse("core:tweets")), "js-add-image")


class AutoGrowMarkupTests(LoggedInTestCase):
    def test_textareas_have_height_cap_and_no_fixed_scrollbar(self):
        make_account()
        tweets = self.client.get(reverse("core:tweets")).content.decode()
        for html in (tweets,):
            tag = html[html.index("<textarea"):html.index(">", html.index("<textarea"))]
            self.assertIn("max-h-[50vh]", tag)
            self.assertIn("overflow-hidden", tag)
            self.assertIn("resize-none", tag)

    def test_reply_textarea_has_height_cap(self):
        acc = make_account()
        mine = Post.objects.create(account=acc, x_id="1", text="t", posted_at=timezone.now(), author_x_id=ME,
                                   author_username="me", author_name="me", is_mine=True)
        Post.objects.create(account=acc, x_id="2", text="r", posted_at=timezone.now(), author_x_id="2",
                            author_username="sub", author_name="s", is_mine=False, in_reply_to_x_id=mine.x_id)
        html = self.client.get(reverse("core:replies")).content.decode()
        tag = html[html.index("<textarea"):html.index(">", html.index("<textarea"))]
        self.assertIn("max-h-[50vh]", tag)


class PreviewZoomMarkupTests(LoggedInTestCase):
    def test_preview_list_is_a_gallery_so_previews_open_the_lightbox(self):
        make_account()
        html = self.client.get(reverse("core:tweets")).content.decode()
        ul = html[html.index('<ul class="js-previews'):]
        ul = ul[:ul.index(">")]
        self.assertIn("js-gallery", ul)
        # 拡大表示の部品は、プレビューと同じページにある
        self.assertIn('id="lightbox"', html)


class ReplyWithImageTests(LoggedInTestCase):
    def setUp(self):
        super().setUp()
        self.account = make_account()
        Post.objects.create(account=self.account, x_id="11", text="t", posted_at=timezone.now(), author_x_id=ME,
                            author_username="me", author_name="me", is_mine=True)
        Post.objects.create(account=self.account, x_id="22", text="r", posted_at=timezone.now(), author_x_id="2",
                            author_username="sub", author_name="s", is_mine=False, in_reply_to_x_id="11")

    def reply(self, data):
        return self.client.post(reverse("core:create_reply"), {"reply_to": "22", **data},
                                headers={"x-requested-with": "XMLHttpRequest"})

    def png(self, name="a.png"):
        return SimpleUploadedFile(name, b"\x89PNG....", content_type="image/png")

    @mock.patch("core.x_api.requests.request")
    def test_reply_with_image_uploads_then_replies(self, req):
        req.side_effect = [
            fake_response(200, {"data": {"id": "mid"}}),
            fake_response(201, {"data": {"id": "90", "text": "どうも"}}),
            fake_response(200, {
                "data": {"id": "90", "text": "@sub どうも https://t.co/MEDIA6789", "author_id": ME,
                         "created_at": "2026-10-18T00:00:00Z", "attachments": {"media_keys": ["k"]},
                         "referenced_tweets": [{"type": "replied_to", "id": "22"}],
                         "entities": {"urls": [{"url": "https://t.co/MEDIA6789", "media_key": "k"}]}},
                "includes": {"media": [{"media_key": "k", "type": "photo", "url": "https://pbs/r.jpg"}]},
            }),
        ]
        resp = self.reply({"text": "どうも", "images": self.png()})
        self.assertEqual(resp.status_code, 200, resp.content)
        upload, create, _fetch = req.call_args_list
        self.assertTrue(upload.args[1].endswith("/media/upload"))
        self.assertEqual(create.kwargs["json"]["media"], {"media_ids": ["mid"]})
        self.assertEqual(create.kwargs["json"]["reply"], {"in_reply_to_tweet_id": "22"})
        saved = Post.objects.get(x_id="90")
        self.assertEqual((saved.text, saved.media_urls, saved.in_reply_to_x_id), ("どうも", ["https://pbs/r.jpg"], "22"))
        self.assertIn("https://pbs/r.jpg", resp.json()["html"])  # 画面の一覧に、画像つきで出る

    @mock.patch("core.x_api.requests.request")
    def test_image_only_reply_is_allowed(self, req):
        req.side_effect = [
            fake_response(200, {"data": {"id": "mid"}}),
            fake_response(201, {"data": {"id": "91", "text": ""}}),
            fake_response(200, {
                "data": {"id": "91", "text": "@sub https://t.co/MEDIA6789", "author_id": ME,
                         "created_at": "2026-10-18T00:00:00Z", "attachments": {"media_keys": ["k"]},
                         "referenced_tweets": [{"type": "replied_to", "id": "22"}]},
                "includes": {"media": [{"media_key": "k", "type": "photo", "url": "https://pbs/r.jpg"}]},
            }),
        ]
        self.assertEqual(self.reply({"text": "", "images": self.png()}).status_code, 200)
        self.assertEqual(Post.objects.get(x_id="91").text, "")  # 「@sub」も残らない

    @mock.patch("core.x_api.requests.request")
    def test_reply_image_validation(self, req):
        self.assertEqual(self.reply({"text": "  "}).json()["field"], "text")
        too_many = [self.png(f"{i}.png") for i in range(5)]
        self.assertEqual(self.reply({"text": "x", "images": too_many}).json()["field"], "images")
        pdf = SimpleUploadedFile("a.pdf", b"x", content_type="application/pdf")
        self.assertEqual(self.reply({"text": "x", "images": pdf}).status_code, 400)
        req.assert_not_called()

    def test_reply_form_has_image_controls(self):
        html = self.client.get(reverse("core:replies")).content.decode()
        form = html[html.index('<div class="js-reply-form'):]
        form = form[:form.index("js-form-error")]
        for needle in ("js-compose-file", "js-add-image", "js-previews", "js-gallery"):
            self.assertIn(needle, form)

    def test_leading_mention_only_text_is_stripped(self):
        item = {"id": "5", "text": "@sub", "author_id": ME, "created_at": "2026-10-18T00:00:00Z",
                "referenced_tweets": [{"type": "replied_to", "id": "22"}]}
        services.save_posts(self.account, {"data": [item]})
        self.assertEqual(Post.objects.get(x_id="5").text, "")
        item2 = {**item, "id": "6", "text": "@sub @other 本文です"}
        services.save_posts(self.account, {"data": [item2]})
        self.assertEqual(Post.objects.get(x_id="6").text, "本文です")

    def test_mention_cleanup_migration(self):
        import importlib

        mod = importlib.import_module("core.migrations.0003_clean_mention_only_replies")
        self.assertTrue(mod.MENTIONS_ONLY.match("@akeno_p"))
        self.assertTrue(mod.MENTIONS_ONLY.match("@a @b"))
        self.assertFalse(mod.MENTIONS_ONLY.match("@akeno_p こんにちは"))


class ReplyBoxLayoutTests(LoggedInTestCase):
    def test_reply_previews_are_inside_the_bordered_box(self):
        acc = make_account()
        mine = Post.objects.create(account=acc, x_id="1", text="t", posted_at=timezone.now(), author_x_id=ME,
                                   author_username="me", author_name="me", is_mine=True)
        Post.objects.create(account=acc, x_id="2", text="r", posted_at=timezone.now(), author_x_id="2",
                            author_username="sub", author_name="s", is_mine=False, in_reply_to_x_id=mine.x_id)
        html = self.client.get(reverse("core:replies")).content.decode()
        form = html[html.index('<div class="js-reply-form'):]
        form = form[:form.index("js-form-error")]
        box = form.index("js-compose-box")
        textarea = form.index("<textarea", box)
        previews = form.index("js-previews", box)
        row = form.index("js-count", box)
        self.assertLess(box, textarea)
        self.assertLess(textarea, previews)
        self.assertLess(previews, row)
        # 枠線は外側の箱だけが持つ
        tag = form[textarea:form.index(">", textarea)]
        self.assertNotIn("border-2", tag)
        self.assertIn("border-2", form[box - 10:box + 160])
        # 箱の閉じタグは、プレビューの後 (プレビューは箱の内側)
        self.assertLess(previews, form.index("</div>", previews))


class ScriptAmountTests(LoggedInTestCase):
    def test_pages_have_no_dollar_amounts(self):
        # JS は各画面の <script> に書いているので、画面全体で確かめる
        make_account()
        for name in ("core:tweets", "core:replies"):
            self.assertNotIn("$0.", self.client.get(reverse(name)).content.decode())


class ParentTweetLinkTests(LoggedInTestCase):
    def setUp(self):
        super().setUp()
        self.account = make_account()

    def thread(self, parent_text, parent_media=(), reply_text="返信です"):
        mine = Post.objects.create(account=self.account, x_id="1", text=parent_text, posted_at=timezone.now(),
                                   author_x_id=ME, author_username="me", author_name="Name me", is_mine=True,
                                   media_urls=list(parent_media))
        Post.objects.create(account=self.account, x_id="2", text=reply_text, posted_at=timezone.now(),
                            author_x_id="2", author_username="sub", author_name="s", is_mine=False,
                            in_reply_to_x_id=mine.x_id)
        html = self.client.get(reverse("core:replies")).content.decode()
        button = html[html.index('class="js-parent-open'):html.index("</button>", html.index('class="js-parent-open'))]
        tpl = html[html.index('<template class="js-parent-tpl">'):html.index("</template>")]
        return button, tpl

    def test_snippet_filter(self):
        from core.templatetags.core_tags import snippet

        self.assertEqual(snippet("短い"), "短い")
        self.assertEqual(snippet("あ" * 20), "あ" * 20)  # ちょうどなら切らない
        self.assertEqual(snippet("あ" * 21), "あ" * 20 + "...")
        self.assertEqual(snippet("一行目\n\n二行目"), "一行目 二行目")  # 改行は空白に直して1行にする
        self.assertEqual(snippet("  "), "")
        self.assertEqual(snippet(None), "")

    def test_long_parent_text_is_cut_with_dots_in_the_heading(self):
        button, _ = self.thread("長すぎるツイートのテキストです。" * 5)
        self.assertIn("...", button)
        self.assertNotIn("長すぎるツイートのテキストです。" * 2, button)

    def test_heading_shows_text_only_even_when_parent_has_images(self):
        button, tpl = self.thread("画像つきです", ["https://pbs/p.jpg"])
        self.assertIn("画像つきです", button)
        self.assertNotIn("<img", button)
        self.assertNotIn("pbs/p.jpg", button)
        self.assertIn("https://pbs/p.jpg", tpl)  # 画像は、ウィンドウの中身にだけある

    def test_image_only_parent_gets_a_placeholder(self):
        button, tpl = self.thread("", ["https://pbs/p.jpg"])
        self.assertIn("(画像のみ)", button)
        self.assertNotIn("<p class=\"mt-1", tpl)  # 本文が空なら、空の段落は出さない

    def test_modal_content_has_full_text_not_truncated(self):
        full = "全文はこちらです。" * 12
        _, tpl = self.thread(full)
        self.assertIn(full, tpl)
        self.assertNotIn("...", tpl)

    def test_heading_is_a_button_and_dialog_exists(self):
        button, _ = self.thread("本文")
        self.assertIn("元のツイートを見る", button)
        html = self.client.get(reverse("core:replies")).content.decode()
        self.assertIn('id="parent-dialog"', html)
        self.assertIn("data-parent-close", html)
        self.assertNotIn("<a ", button)

    def test_text_with_html_is_escaped_in_modal(self):
        _, tpl = self.thread("<script>alert(1)</script>")
        self.assertNotIn("<script>alert(1)</script>", tpl)
        self.assertIn("&lt;script&gt;", tpl)
