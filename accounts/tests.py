import time

import pyotp
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from .models import TotpDevice

User = get_user_model()


class AuthFlowTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("owner", password="correct-horse-1")

    def login(self, password="correct-horse-1", **kwargs):
        return self.client.post(
            reverse("accounts:login"), {"username": "owner", "password": password}, **kwargs
        )

    def test_anonymous_is_sent_to_login(self):
        for name in ("core:tweets", "core:replies"):
            resp = self.client.get(reverse(name))
            self.assertRedirects(resp, reverse("accounts:login"), fetch_redirect_response=False)

    def test_anonymous_api_gets_403_json(self):
        resp = self.client.post(
            reverse("core:create_tweet"), {"text": "x"}, headers={"x-requested-with": "XMLHttpRequest"}
        )
        self.assertEqual(resp.status_code, 403)

    def test_wrong_password(self):
        resp = self.login("nope", follow=True)
        self.assertContains(resp, "ユーザー名またはパスワードが間違っています")

    def test_failed_login_redirects_so_reload_does_not_resubmit(self):
        """失敗結果を POST の応答として直接返すと、リロードで「フォーム再送信」になる。"""
        resp = self.login("nope")
        self.assertRedirects(resp, reverse("accounts:login"), fetch_redirect_response=False)

        shown = self.client.get(reverse("accounts:login"))
        self.assertContains(shown, "ユーザー名またはパスワードが間違っています")
        self.assertContains(shown, 'value="owner"')  # ユーザー名は打ち直さなくて済む

        reloaded = self.client.get(reverse("accounts:login"))  # = リロード
        self.assertNotContains(reloaded, "間違っています")
        self.assertNotContains(reloaded, 'aria-invalid="true"')

    def test_password_is_never_stored_in_the_session(self):
        self.login("wrong-password-xyz")
        self.assertNotIn("wrong-password-xyz", str(dict(self.client.session)))

    def test_failed_otp_redirects_and_message_disappears_on_reload(self):
        self.login()
        self.client.get(reverse("accounts:two_factor"))
        resp = self.client.post(reverse("accounts:two_factor"), {"code": "000000"})
        self.assertRedirects(resp, reverse("accounts:two_factor"), fetch_redirect_response=False)
        self.assertContains(self.client.get(reverse("accounts:two_factor")), "認証コードが正しくありません")
        self.assertNotContains(self.client.get(reverse("accounts:two_factor")), "正しくありません")

    def test_login_error_does_not_reveal_which_field_is_wrong(self):
        """ユーザー名が違う場合も、パスワードだけが違う場合も、画面の出力は同じ。"""

        def error_view(username, password):
            html = self.client.post(
                reverse("accounts:login"), {"username": username, "password": password}, follow=True
            ).content.decode()
            # 入力欄に戻されるユーザー名だけは入力した本人の文字列なので、比較から除く
            return html.replace(f'value="{username}"', 'value=""')

        cache.clear()
        wrong_password = error_view("owner", "wrong-password")
        cache.clear()
        wrong_user = error_view("nobody", "wrong-password")
        # CSRFトークンはリクエストごとに変わるので除く
        import re

        strip = lambda h: re.sub(r'(name="csrfmiddlewaretoken" value|name="csrf-token" content)="[^"]*"', "", h)
        self.assertEqual(strip(wrong_password), strip(wrong_user))
        # 両方の入力欄が赤くなり、文言は「または」で両方を指す
        self.assertEqual(wrong_password.count('aria-invalid="true"'), 2)
        self.assertIn("ユーザー名またはパスワードが間違っています", wrong_password)

    def test_login_lock_message_is_text_only_and_same_for_any_username(self):
        for name in ("owner", "nobody"):
            cache.clear()
            for _ in range(5):
                self.client.post(reverse("accounts:login"), {"username": name, "password": "x"})
            resp = self.client.post(
                reverse("accounts:login"), {"username": name, "password": "x"}, follow=True
            )
            self.assertContains(resp, "しばらくお待ちください")
            self.assertNotContains(resp, 'aria-invalid="true"')

    def post_login_followed(self, username, password):
        return self.client.post(
            reverse("accounts:login"), {"username": username, "password": password}, follow=True
        )

    def test_empty_username_marks_only_username(self):
        resp = self.post_login_followed("", "something")
        self.assertContains(resp, "ユーザー名が空欄です")
        html = resp.content.decode()
        self.assertEqual(html.count('aria-invalid="true"'), 1)
        self.assertRegex(html, r'id="username"[^>]*aria-invalid="true"')

    def test_empty_password_marks_only_password(self):
        resp = self.post_login_followed("owner", "")
        self.assertContains(resp, "パスワードが空欄です")
        html = resp.content.decode()
        self.assertEqual(html.count('aria-invalid="true"'), 1)
        self.assertRegex(html, r'id="password"[^>]*aria-invalid="true"')
        self.assertContains(resp, 'value="owner"')

    def test_both_empty_marks_both(self):
        resp = self.post_login_followed("", "")
        self.assertContains(resp, "ユーザー名とパスワードが空欄です")
        self.assertEqual(resp.content.decode().count('aria-invalid="true"'), 2)

    def test_whitespace_only_username_counts_as_empty(self):
        self.assertContains(self.post_login_followed("   ", "x"), "ユーザー名が空欄です")

    def test_empty_fields_do_not_count_toward_lockout(self):
        for _ in range(10):
            self.post_login_followed("owner", "")
        resp = self.login(follow=True)  # 正しい資格情報ならそのまま進める
        self.assertRedirects(resp, reverse("accounts:two_factor"))

    def test_empty_otp_code(self):
        self.login()
        self.client.get(reverse("accounts:two_factor"))
        resp = self.client.post(reverse("accounts:two_factor"), {"code": "  "}, follow=True)
        self.assertContains(resp, "認証コードが空欄です")
        self.assertContains(resp, 'aria-invalid="true"')

    def test_error_area_is_always_rendered_to_keep_layout_stable(self):
        """エラーがなくても文章の置き場があり、出現しても下の要素が動かない。"""
        self.assertContains(self.client.get(reverse("accounts:login")), 'id="form-error"')
        self.login()
        self.assertContains(self.client.get(reverse("accounts:two_factor")), 'id="form-error"')

    def test_login_locks_after_repeated_failures(self):
        for _ in range(5):
            self.login("nope")
        resp = self.login("correct-horse-1", follow=True)  # 正しくても拒否される
        self.assertContains(resp, "しばらくお待ちください")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_password_alone_does_not_open_the_app(self):
        self.assertRedirects(self.login(), reverse("accounts:two_factor"), fetch_redirect_response=False)
        resp = self.client.get(reverse("core:tweets"))
        self.assertRedirects(resp, reverse("accounts:two_factor"), fetch_redirect_response=False)

    def test_setup_shows_qr_then_code_confirms(self):
        self.login()
        resp = self.client.get(reverse("accounts:two_factor"))
        self.assertContains(resp, "<svg")
        self.assertContains(resp, "2段階認証 設定")

        device = TotpDevice.objects.get(user=self.user)
        self.assertFalse(device.confirmed)
        code = pyotp.TOTP(device.secret).now()
        resp = self.client.post(reverse("accounts:two_factor"), {"code": code})
        self.assertRedirects(resp, reverse("core:tweets"), fetch_redirect_response=False)
        device.refresh_from_db()
        self.assertTrue(device.confirmed)
        self.assertEqual(self.client.get(reverse("core:tweets")).status_code, 200)

    def test_wrong_code_is_rejected(self):
        self.login()
        self.client.get(reverse("accounts:two_factor"))
        resp = self.client.post(reverse("accounts:two_factor"), {"code": "000000"}, follow=True)
        self.assertContains(resp, "認証コードが正しくありません")
        self.assertContains(resp, 'aria-invalid="true"')
        self.assertFalse(self.client.session.get("two_factor_verified"))

    def test_same_code_cannot_be_reused(self):
        device = TotpDevice.objects.create(user=self.user, secret=TotpDevice.new_secret(), confirmed=True)
        code = pyotp.TOTP(device.secret).now()
        self.login()
        self.assertRedirects(
            self.client.post(reverse("accounts:two_factor"), {"code": code}),
            reverse("core:tweets"),
            fetch_redirect_response=False,
        )
        self.client.post(reverse("accounts:logout"))
        self.login()
        resp = self.client.post(reverse("accounts:two_factor"), {"code": code}, follow=True)
        self.assertContains(resp, "認証コードが正しくありません")

    def test_confirmed_device_shows_input_screen_not_qr(self):
        TotpDevice.objects.create(user=self.user, secret=TotpDevice.new_secret(), confirmed=True)
        self.login()
        resp = self.client.get(reverse("accounts:two_factor"))
        self.assertNotContains(resp, "<svg viewBox")
        self.assertContains(resp, "認証アプリに表示されている6桁")

    def test_code_with_hyphen_is_accepted(self):
        device = TotpDevice.objects.create(user=self.user, secret=TotpDevice.new_secret(), confirmed=True)
        code = pyotp.TOTP(device.secret).now()
        self.login()
        resp = self.client.post(reverse("accounts:two_factor"), {"code": f"{code[:3]}-{code[3:]}"})
        self.assertRedirects(resp, reverse("core:tweets"), fetch_redirect_response=False)

    def test_otp_locks_after_repeated_failures(self):
        device = TotpDevice.objects.create(user=self.user, secret=TotpDevice.new_secret(), confirmed=True)
        self.login()
        for _ in range(5):
            self.client.post(reverse("accounts:two_factor"), {"code": "111111"})
        resp = self.client.post(
            reverse("accounts:two_factor"), {"code": pyotp.TOTP(device.secret).now()}, follow=True
        )
        self.assertContains(resp, "しばらくお待ちください")

    def test_logout_requires_post(self):
        self.login()
        self.assertEqual(self.client.get(reverse("accounts:logout")).status_code, 405)


class Reset2faCommandTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("owner", password="correct-horse-1")
        self.device = TotpDevice.objects.create(user=self.user, secret=TotpDevice.new_secret(), confirmed=True)

    def run_command(self, *args):
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("reset_2fa", *args, stdout=out)
        return out.getvalue()

    def test_reset_then_login_shows_qr_setup_again(self):
        self.run_command()  # ユーザーが1人なので省略できる
        self.assertFalse(TotpDevice.objects.filter(user=self.user).exists())

        self.client.post(reverse("accounts:login"), {"username": "owner", "password": "correct-horse-1"})
        resp = self.client.get(reverse("accounts:two_factor"))
        self.assertContains(resp, "2段階認証 設定")
        self.assertContains(resp, "<svg")
        # 新しい秘密鍵になっている (古い認証アプリのコードは使えない)
        new = TotpDevice.objects.get(user=self.user)
        self.assertNotEqual(new.secret, self.device.secret)

    def test_reset_does_not_touch_password(self):
        self.run_command("owner")
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("correct-horse-1"))

    def test_reset_explains_how_to_clear_lockout(self):
        # ロックは起動中のサーバーのメモリにあり、別プロセスのこのコマンドからは消せないので、解除方法を案内する
        self.assertIn("サーバーを再起動", self.run_command())

    def test_requires_username_when_multiple_users(self):
        from django.core.management.base import CommandError

        User.objects.create_user("another", password="x-correct-horse-2")
        with self.assertRaises(CommandError):
            self.run_command()
        self.run_command("owner")
        self.assertFalse(TotpDevice.objects.filter(user=self.user).exists())

    def test_unknown_user(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            self.run_command("nobody")
