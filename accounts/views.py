from django.contrib.auth import authenticate, login, logout
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from . import throttle
from .middleware import SESSION_KEY
from .models import TotpDevice
from .qr import svg_data


def _client_ip(request):
    return request.META.get("REMOTE_ADDR", "")


def _fail(error, fields):
    """失敗の理由と、赤くする入力欄の名前を返す。"""
    return JsonResponse({"error": error, "fields": fields}, status=400)


def _go(url_name):
    """成功。JS が redirect の URL へ画面を移す。"""
    return JsonResponse({"redirect": reverse(url_name)})


LOCKED_MESSAGE = "失敗が続いたため、しばらくお待ちください"  # 1行に収まる長さにする


def _empty_login_fields(username, password):
    """空欄の入力欄の名前を返す。空欄かどうかは、認証の正否とは無関係な情報。"""
    fields = []
    if not username:
        fields.append("username")
    if not password:
        fields.append("password")
    return fields

# レビューした
@require_GET
def login_page(request):
    """ログイン画面の表示 (GET)"""
    if request.user.is_authenticated and request.session.get(SESSION_KEY):
        return redirect("core:tweets")
    return render(request, "accounts/login.html")


@require_POST
def login_api(request):
    """ログイン認証処理 (POST)"""
    if request.user.is_authenticated and request.session.get(SESSION_KEY):
        return redirect("core:tweets")

    username = request.POST.get("username", "").strip()
    password = request.POST.get("password", "")

    empty = _empty_login_fields(username, password)
    if empty:
        if not username and not password:
            message = "ユーザー名とパスワードが空欄です"
        elif not username:
            message = "ユーザー名が空欄です"
        else:
            message = "パスワードが空欄です"
        return _fail(message, empty)

    ident = f"{_client_ip(request)}:{username.lower()}"
    if throttle.is_locked("login", ident):
        return _fail(LOCKED_MESSAGE, [])  # ロック中は入力欄を赤くしない

    user = authenticate(request, username=username, password=password)
    if user is None:
        throttle.record_failure("login", ident)
        # どちらが違うのかは伝えない (ユーザー名の存在を推測されないため)
        return _fail(
            "ユーザー名またはパスワードが間違っています", ["username", "password"]
        )

    throttle.reset("login", ident)
    login(request, user)  # セッションIDは入れ替わる
    request.session[SESSION_KEY] = False
    return _go("accounts:two_factor")


@require_GET
def two_factor_page(request):
    """2段階認証画面の表示 (GET)"""
    if not request.user.is_authenticated:
        return redirect("accounts:login")
    if request.session.get(SESSION_KEY):
        return redirect("core:tweets")

    device = TotpDevice.objects.filter(user=request.user).first()
    if device is None:
        device = TotpDevice.objects.create(
            user=request.user, secret=TotpDevice.new_secret()
        )
    setting_up = not device.confirmed

    context = {"setting_up": setting_up}
    if setting_up:
        context["qr_svg"] = svg_data(device.provisioning_uri())
    return render(request, "accounts/two_factor.html", context)


@require_POST
def two_factor_api(request):
    """2段階認証コードの検証処理 (POST)"""
    if not request.user.is_authenticated:
        return redirect("accounts:login")
    if request.session.get(SESSION_KEY):
        return redirect("core:tweets")

    device = TotpDevice.objects.filter(user=request.user).first()
    if device is None:
        return _fail("2段階認証が初期化されていません", ["code"])

    setting_up = not device.confirmed
    code = request.POST.get("code", "")
    if not code.strip():
        return _fail("認証コードが空欄です", ["code"])

    ident = str(request.user.pk)
    if throttle.is_locked("otp", ident):
        return _fail(LOCKED_MESSAGE, [])

    if device.verify(code):
        throttle.reset("otp", ident)
        if setting_up:
            device.confirmed = True
            device.save(update_fields=["confirmed"])
        request.session[SESSION_KEY] = True
        return _go("core:tweets")

    throttle.record_failure("otp", ident)
    return _fail("認証コードが正しくありません", ["code"])


@require_POST
def logout_view(request):
    logout(request)
    return _go("accounts:login")
