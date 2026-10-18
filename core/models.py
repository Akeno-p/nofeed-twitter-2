from django.db import models


class XAccount(models.Model):
    """連携している X アカウント。is_active が True のものを画面に表示する。"""

    x_user_id = models.CharField(max_length=32, unique=True)
    username = models.CharField(max_length=32)
    name = models.CharField(max_length=100)
    profile_image_url = models.URLField(blank=True)
    access_token = models.TextField()
    refresh_token = models.TextField(blank=True)
    expires_at = models.DateTimeField()
    is_active = models.BooleanField(default=False)
    # 次回の取得で「これより新しいものだけ」を取るための目印 (API の料金を抑える)
    since_own_id = models.CharField(max_length=32, blank=True)
    since_reply_id = models.CharField(max_length=32, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"@{self.username}"


class Post(models.Model):
    """X から取得した (または自分で投稿した) ツイートのキャッシュ。

    自分のツイート・自分の返信・他人から来た返信を、すべてこの1テーブルに入れる。
    """

    account = models.ForeignKey(XAccount, on_delete=models.CASCADE, related_name="posts")
    x_id = models.CharField(max_length=32)
    text = models.TextField()
    posted_at = models.DateTimeField()
    author_x_id = models.CharField(max_length=32)
    author_username = models.CharField(max_length=32)
    author_name = models.CharField(max_length=100)
    author_avatar = models.URLField(blank=True)
    is_mine = models.BooleanField()
    in_reply_to_x_id = models.CharField(max_length=32, null=True, blank=True)
    media_urls = models.JSONField(default=list)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["account", "x_id"], name="uniq_post_per_account")
        ]
        indexes = [models.Index(fields=["account", "-posted_at"])]
        ordering = ["-posted_at"]

    def __str__(self):
        return f"{self.x_id} {self.text[:20]}"
