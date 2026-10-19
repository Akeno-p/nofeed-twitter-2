"""2段階認証をリセットする。認証アプリのコードを消してしまったときなどに使う。

リセットすると、次回ログイン時に QR コードの登録画面が出る。
サーバーを操作できる人 (= このPCを使える人) だけが実行できる。
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from accounts.models import TotpDevice


class Command(BaseCommand):
    help = "ユーザーの2段階認証をリセットする (次回ログイン時に再登録する)"

    def add_arguments(self, parser):
        parser.add_argument(
            "username",
            nargs="?",
            help="対象のユーザー名。ユーザーが1人だけなら省略できる",
        )

    def handle(self, *args, **options):
        User = get_user_model()
        username = options["username"]
        if username:
            user = User.objects.filter(username=username).first()
            if user is None:
                raise CommandError("そのユーザー名のユーザーが見つかりません。")
        else:
            users = list(User.objects.all()[:2])
            if len(users) != 1:
                raise CommandError(
                    "ユーザーが複数 (または0人) です。ユーザー名を指定してください。"
                )
            user = users[0]

        deleted, _ = TotpDevice.objects.filter(user=user).delete()

        if deleted:
            self.stdout.write(
                self.style.SUCCESS(
                    "2段階認証をリセットしました。次回ログイン時にQRコードの登録画面が出ます。"
                )
            )
        else:
            self.stdout.write(
                "2段階認証は未登録でした。次回ログイン時にQRコードの登録画面が出ます。"
            )
        # 失敗回数のロックは、起動中のサーバーのメモリにある。このコマンドは別のプロセスで動くので消せない。
        self.stdout.write(
            "失敗が続いてロックされている場合は、サーバーを再起動すると解除されます (5分待っても解除されます)。"
        )
