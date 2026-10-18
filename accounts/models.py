import time

import pyotp
from django.conf import settings
from django.db import models


class TotpDevice(models.Model):
    """ユーザーごとの2段階認証 (TOTP) の設定。confirmed=True で有効。"""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="totp_device"
    )
    secret = models.CharField(max_length=64)
    confirmed = models.BooleanField(default=False)
    # 同じコードの使い回し (リプレイ) を防ぐため、最後に使った30秒枠を覚える
    last_used_step = models.BigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    @classmethod
    def new_secret(cls):
        return pyotp.random_base32()

    def provisioning_uri(self):
        return pyotp.TOTP(self.secret).provisioning_uri(
            name=self.user.get_username(), issuer_name="nofeed-twitter"
        )

    def verify(self, code):
        """コードが正しく、かつ未使用なら True。使った枠は記録する。"""
        code = "".join(ch for ch in str(code) if ch.isdigit())
        if len(code) != 6:
            return False
        totp = pyotp.TOTP(self.secret)
        # 前後1枠 (±30秒) の時刻ずれを許容
        now_step = int(time.time()) // totp.interval
        for step in (now_step - 1, now_step, now_step + 1):
            if step <= self.last_used_step:
                continue
            if totp.at(step * totp.interval) == code:
                self.last_used_step = step
                self.save(update_fields=["last_used_step"])
                return True
        return False
