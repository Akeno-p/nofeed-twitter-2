from django.db import models, transaction
from django.db.models import Q

from . import x_api


class XAccountManager(models.Manager):
    def active(self):
        """画面に表示しているアカウント。連携が無ければ None。"""
        return self.filter(is_active=True).first()


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

    objects = XAccountManager()

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"@{self.username}"

    @classmethod
    def connect(cls, me, token):
        """連携したアカウントを作成 (連携済みなら更新) して、表示中にする。"""
        with transaction.atomic():
            account = cls.objects.filter(x_user_id=me["id"]).first() or cls(x_user_id=me["id"])
            account.username = me["username"]
            account.name = me["name"]
            account.profile_image_url = me.get("profile_image_url", "")
            x_api.apply_new_token(account, token)
            cls.objects.update(is_active=False)
            account.is_active = True
            account.save()
        return account

    def activate(self):
        """このアカウントを表示中にする。表示中のアカウントは常に1つだけ。"""
        with transaction.atomic():
            XAccount.objects.update(is_active=False)
            self.is_active = True
            self.save(update_fields=["is_active"])

    def disconnect(self):
        """連携を削除する。表示中だったら、残りのアカウントの先頭を表示中にする。"""
        with transaction.atomic():
            self.delete()  # 保存していたツイートも一緒に消える
            if self.is_active:
                nxt = XAccount.objects.first()
                if nxt:
                    nxt.is_active = True
                    nxt.save(update_fields=["is_active"])


class PostManager(models.Manager):
    def my_post_ids(self, account):
        return self.filter(account=account, is_mine=True).values("x_id")

    def own_tweets(self, account):
        """トップ画面用: 自分のツイート (他人への返信は除く)。"""
        return (
            self.filter(account=account, is_mine=True)
            .filter(Q(in_reply_to_x_id__isnull=True) | Q(in_reply_to_x_id__in=self.my_post_ids(account)))
            .order_by("-posted_at")[:200]
        )

    def replies_to_me(self, account):
        """自分のツイートへ来た返信。"""
        return self.filter(account=account, is_mine=False, in_reply_to_x_id__in=self.my_post_ids(account))

    def reply_threads(self, account):
        """リプライ画面用: 自分のツイートへ来た返信と、それへの自分の返事。"""
        mine = {p.x_id: p for p in self.filter(account=account, is_mine=True)}
        incoming = list(
            self.filter(account=account, is_mine=False, in_reply_to_x_id__in=list(mine))
            .order_by("-posted_at")[:200]
        )
        answers = {}
        for p in sorted(
            (p for p in mine.values() if p.in_reply_to_x_id), key=lambda p: p.posted_at
        ):
            answers.setdefault(p.in_reply_to_x_id, []).append(p)
        return [
            {"reply": r, "parent": mine[r.in_reply_to_x_id], "answers": answers.get(r.x_id, [])}
            for r in incoming
        ]

    def prune_unrelated_replies(self, account):
        """自分の投稿への返信でないもの (返信先が手元に無いもの) を消す。"""
        self.filter(account=account, is_mine=False).exclude(in_reply_to_x_id__in=self.my_post_ids(account)).delete()


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

    objects = PostManager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["account", "x_id"], name="uniq_post_per_account")
        ]
        indexes = [models.Index(fields=["account", "-posted_at"])]
        ordering = ["-posted_at"]

    def __str__(self):
        return f"{self.x_id} {self.text[:20]}"
