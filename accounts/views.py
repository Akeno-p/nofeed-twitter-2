from django.contrib.auth import authenticate, login, logout
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from . import throttle
from .middleware import SESSION_KEY
from .models import TotpDevice
from .qr import svg_data


def _client_ip(request):
    return request.META.get("REMOTE_ADDR", "")


def _fail_and_redirect(request, key, url_name, **state):
    """失敗結果を1回だけ表示できるよう保存し、同じ画面へ GET で戻す。

    POST の結果をそのまま描画すると、リロードで「フォーム再送信」になってしまう。
    パスワードやコードは保存しない。
    """
    request.session[key] = state
    return redirect(url_name)


LOCKED_MESSAGE = "失敗が続いたため、しばらくお待ちください"  # 1行に収まる長さにする


def _empty_login_fields(username, password):
    """空欄の入力欄の名前を返す。空欄かどうかは、認証の正否とは無関係な情報。"""
    fields = []
    if not username:
        fields.append("username")
    if not password:
        fields.append("password")
    return fields


@require_http_methods(["GET", "POST"])
def login_view(request):
    if request.user.is_authenticated and request.session.get(SESSION_KEY):
        return redirect("core:tweets")

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")

        empty = _empty_login_fields(username, password)
        if empty:
            # 空欄は認証を試していないので、失敗回数には数えない
            message = {
                ("username",): "ユーザー名が空欄です",
                ("password",): "パスワードが空欄です",
            }.get(tuple(empty), "ユーザー名とパスワードが空欄です")
            return _fail_and_redirect(
                request, "login_flash", "accounts:login",
                error=message, fields=empty, username=username,
            )

        ident = f"{_client_ip(request)}:{username.lower()}"
        if throttle.is_locked("login", ident):
            return _fail_and_redirect(
                request, "login_flash", "accounts:login",
                error=LOCKED_MESSAGE,
                fields=[],  # ロック中は入力欄を赤くしない
                username=username,
            )
        user = authenticate(request, username=username, password=password)
        if user is None:
            throttle.record_failure("login", ident)
            # どちらが違うのかは伝えない (ユーザー名の存在を推測されないため)
            return _fail_and_redirect(
                request, "login_flash", "accounts:login",
                error="ユーザー名またはパスワードが間違っています",
                fields=["username", "password"],
                username=username,
            )
        throttle.reset("login", ident)
        login(request, user)  # セッションIDは入れ替わる
        request.session[SESSION_KEY] = False
        return redirect("accounts:two_factor")

    flash = request.session.pop("login_flash", {})  # 1回見たら消える
    return render(
        request,
        "accounts/login.html",
        {
            "error": flash.get("error"),
            "invalid_fields": flash.get("fields", []),
            "username": flash.get("username", ""),
        },
    )


@require_http_methods(["GET", "POST"])
def two_factor_view(request):
    """未設定なら QR コードの登録画面、設定済みならコード入力画面になる。"""
    if not request.user.is_authenticated:
        return redirect("accounts:login")
    if request.session.get(SESSION_KEY):
        return redirect("core:tweets")

    device = TotpDevice.objects.filter(user=request.user).first()
    if device is None:
        device = TotpDevice.objects.create(user=request.user, secret=TotpDevice.new_secret())
    setting_up = not device.confirmed

    if request.method == "POST":
        code = request.POST.get("code", "")
        if not code.strip():
            return _fail_and_redirect(
                request, "otp_flash", "accounts:two_factor",
                error="認証コードが空欄です", fields=["code"],
            )
        ident = str(request.user.pk)
        if throttle.is_locked("otp", ident):
            return _fail_and_redirect(
                request, "otp_flash", "accounts:two_factor",
                error=LOCKED_MESSAGE, fields=[],
            )
        if device.verify(code):
            throttle.reset("otp", ident)
            if setting_up:
                device.confirmed = True
                device.save(update_fields=["confirmed"])
            request.session[SESSION_KEY] = True
            return redirect("core:tweets")
        throttle.record_failure("otp", ident)
        return _fail_and_redirect(
            request, "otp_flash", "accounts:two_factor",
            error="認証コードが正しくありません",
            fields=["code"],
        )

    flash = request.session.pop("otp_flash", {})
    context = {
        "setting_up": setting_up,
        "error": flash.get("error"),
        "invalid_fields": flash.get("fields", []),
    }
    if setting_up:
        context["qr_svg"] = svg_data(device.provisioning_uri())
    return render(request, "accounts/two_factor.html", context)


@require_POST
def logout_view(request):
    logout(request)
    return redirect("accounts:login")
