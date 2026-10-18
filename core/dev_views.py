"""開発中のデザイン確認用ページ。DEBUG=True のときだけ開ける (それ以外は 404)。

実際の秘密鍵やトークンは一切使わず、ダミーの値で画面を描画する。
"""

from functools import wraps

import pyotp
from django.conf import settings
from django.http import Http404
from django.shortcuts import render

from accounts.qr import svg_data
from accounts.views import LOCKED_MESSAGE


def debug_only(view):
    # URL は常に登録しておき、リクエスト時に DEBUG を見る (設定を切り替えても確実に閉じるため)
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not settings.DEBUG:
            raise Http404
        return view(request, *args, **kwargs)

    return wrapper


@debug_only
def index(request):
    return render(request, "dev/index.html")


# 2段階認証画面で見られるエラー表示 (キー は ?error= に指定する)
OTP_ERRORS = {
    "invalid": ("認証コードが正しくありません", ["code"]),
    "empty": ("認証コードが空欄です", ["code"]),
    "locked": (LOCKED_MESSAGE, []),
}


@debug_only
def two_factor_setup(request):
    """2段階認証の登録 (QRコード) 画面。QRは今この場で作ったダミーで、保存しない。"""
    error, fields = OTP_ERRORS.get(request.GET.get("error"), (None, []))
    dummy = pyotp.TOTP(pyotp.random_base32()).provisioning_uri(
        name="preview", issuer_name="nofeed-twitter"
    )
    return render(
        request,
        "accounts/two_factor.html",
        {"setting_up": True, "qr_svg": svg_data(dummy), "error": error, "invalid_fields": fields},
    )


@debug_only
def x_connect(request):
    """Xアカウントが未連携のときの画面。連携中のアカウントがあっても、未連携として描画する。

    ?configured=0 で「.env が未設定」の案内、?flash=1 で連携失敗のメッセージを見られる。
    """
    context = {
        "nav": "tweets",
        "tweets": [],
        # 画面共通の部品 (core.context_processors) の値を上書きして、未連携の状態にする
        "x_account": None,
        "x_accounts": [],
        "x_configured": request.GET.get("configured") != "0",
        "flash": "連携に失敗しました。もう一度お試しください。" if request.GET.get("flash") else None,
        "tweet_max_length": settings.TWEET_MAX_LENGTH,
    }
    return render(request, "core/tweets.html", context)
