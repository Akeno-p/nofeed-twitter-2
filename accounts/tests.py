import time

import pyotp
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from .models import TotpDevice
from .views import LOCKED_MESSAGE

User = get_user_model()


class AuthFlowTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("owner", password="correct-horse-1")

    def login(self, password="correct-horse-1", username="owner"):
        return self.client.post(reverse("accounts:login"), {"username": username, "password": password})

    def otp(self, code):
        return self.client.post(reverse("accounts:two_factor"), {"code": code})

    def assertGoes(self, resp, url_name):
        """成功: JS が移る先の URL を JSON で返す。"""
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"redirect": reverse(url_name)})

    def assertFails(self, resp, error, fields):
        """失敗: 理由と、赤くする入力欄の名前を JSON で返す。"""
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json(), {"error": error, "fields": fields})

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
        self.assertFails(self.login("nope"), "ユーザー名またはパスワードが間違っています", ["username", "password"])

    def test_password_is_never_stored_in_the_session(self):
        self.login("wrong-password-xyz")
        self.assertNotIn("wrong-password-xyz", str(dict(self.client.session)))

    def test_login_error_does_not_reveal_which_field_is_wrong(self):
        """ユーザー名が違う場合も、パスワードだけが違う場合も、返す内容は同じ。"""
        cache.clear()
        wrong_password = self.login("wrong-password").json()
        cache.clear()
        wrong_user = self.login("wrong-password", username="nobody").json()
        self.assertEqual(wrong_password, wrong_user)

    def test_login_lock_message_is_text_only_and_same_for_any_username(self):
        for name in ("owner", "nobody"):
            cache.clear()
            for _ in range(5):
                self.login("x", username=name)
            self.assertFails(self.login("x", username=name), LOCKED_MESSAGE, [])  # 入力欄は赤くしない

    def test_empty_username_marks_only_username(self):
        self.assertFails(self.login("something", username=""), "ユーザー名が空欄です", ["username"])

    def test_empty_password_marks_only_password(self):
        self.assertFails(self.login(""), "パスワードが空欄です", ["password"])

    def test_both_empty_marks_both(self):
        self.assertFails(self.login("", username=""), "ユーザー名とパスワードが空欄です", ["username", "password"])

    def test_whitespace_only_username_counts_as_empty(self):
        self.assertFails(self.login("x", username="   "), "ユーザー名が空欄です", ["username"])

    def test_empty_fields_do_not_count_toward_lockout(self):
        for _ in range(10):
            self.login("")
        self.assertGoes(self.login(), "accounts:two_factor")  # 正しい資格情報ならそのまま進める

    def test_empty_otp_code(self):
        self.login()
        self.client.get(reverse("accounts:two_factor"))
        self.assertFails(self.otp("  "), "認証コードが空欄です", ["code"])

    def test_error_area_is_always_rendered_to_keep_layout_stable(self):
        """エラーがなくても文章の置き場があり、出現しても下の要素が動かない。"""
        self.assertContains(self.client.get(reverse("accounts:login")), 'id="form-error"')
        self.login()
        self.assertContains(self.client.get(reverse("accounts:two_factor")), 'id="form-error"')

    def test_login_locks_after_repeated_failures(self):
        for _ in range(5):
            self.login("nope")
        self.assertFails(self.login(), LOCKED_MESSAGE, [])  # 正しくても拒否される
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_password_alone_does_not_open_the_app(self):
        self.assertGoes(self.login(), "accounts:two_factor")
        resp = self.client.get(reverse("core:tweets"))
        self.assertRedirects(resp, reverse("accounts:two_factor"), fetch_redirect_response=False)

    def test_setup_shows_qr_then_code_confirms(self):
        self.login()
        resp = self.client.get(reverse("accounts:two_factor"))
        self.assertContains(resp, "<svg")
        self.assertContains(resp, "2段階認証 設定")

        device = TotpDevice.objects.get(user=self.user)
        self.assertFalse(device.confirmed)
        self.assertGoes(self.otp(pyotp.TOTP(device.secret).now()), "core:tweets")
        device.refresh_from_db()
        self.assertTrue(device.confirmed)
        self.assertEqual(self.client.get(reverse("core:tweets")).status_code, 200)

    def test_wrong_code_is_rejected(self):
        self.login()
        self.client.get(reverse("accounts:two_factor"))
        self.assertFails(self.otp("000000"), "認証コードが正しくありません", ["code"])
        self.assertFalse(self.client.session.get("two_factor_verified"))

    def test_same_code_cannot_be_reused(self):
        device = TotpDevice.objects.create(user=self.user, secret=TotpDevice.new_secret(), confirmed=True)
        code = pyotp.TOTP(device.secret).now()
        self.login()
        self.assertGoes(self.otp(code), "core:tweets")
        self.client.post(reverse("accounts:logout"))
        self.login()
        self.assertFails(self.otp(code), "認証コードが正しくありません", ["code"])

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
        self.assertGoes(self.otp(f"{code[:3]}-{code[3:]}"), "core:tweets")

    def test_otp_locks_after_repeated_failures(self):
        device = TotpDevice.objects.create(user=self.user, secret=TotpDevice.new_secret(), confirmed=True)
        self.login()
        for _ in range(5):
            self.otp("111111")
        self.assertFails(self.otp(pyotp.TOTP(device.secret).now()), LOCKED_MESSAGE, [])

    def test_logout_requires_post(self):
        self.login()
        self.assertEqual(self.client.get(reverse("accounts:logout")).status_code, 405)

    def test_logout_returns_login_url(self):
        self.login()
        self.assertGoes(self.client.post(reverse("accounts:logout")), "accounts:login")
        self.assertNotIn("_auth_user_id", self.client.session)


class AdminAccessTests(TestCase):
    """管理画面も、ログインと2段階認証を通った管理者だけが開ける。"""

    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_superuser("owner", password="correct-horse-1")

    def test_anonymous_is_sent_to_login(self):
        resp = self.client.get("/admin/")
        self.assertRedirects(resp, reverse("accounts:login"), fetch_redirect_response=False)

    def test_password_alone_does_not_open_admin(self):
        self.client.post(reverse("accounts:login"), {"username": "owner", "password": "correct-horse-1"})
        resp = self.client.get("/admin/")
        self.assertRedirects(resp, reverse("accounts:two_factor"), fetch_redirect_response=False)

    def test_admin_opens_after_two_factor(self):
        device = TotpDevice.objects.create(user=self.admin, secret=TotpDevice.new_secret(), confirmed=True)
        self.client.post(reverse("accounts:login"), {"username": "owner", "password": "correct-horse-1"})
        self.client.post(reverse("accounts:two_factor"), {"code": pyotp.TOTP(device.secret).now()})
        self.assertEqual(self.client.get("/admin/").status_code, 200)


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
