import logging
import secrets
from functools import wraps
from urllib.parse import urlparse

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.views.decorators.http import require_POST

from . import services, x_api
from .models import Post, XAccount

logger = logging.getLogger(__name__)


def _json_error(message, status=400, **extra):
    return JsonResponse({"error": message, **extra}, status=status)


def api_view(view):
    """API 用の共通処理: 連携済みアカウントを渡し、X/入力のエラーを JSON で返す。"""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        account = XAccount.objects.active()
        if account is None:
            return _json_error(
                "Xアカウントが連携されていません。", needs_reconnect=True
            )
        try:
            return view(request, account, *args, **kwargs)
        except services.ValidationError as exc:
            return _json_error(str(exc), field=exc.field)
        except x_api.XApiError as exc:
            return _json_error(
                exc.message, status=502, needs_reconnect=exc.needs_reconnect
            )

    return wrapper


# ---------- ページ ----------


def _sync_prices():
    """取得ボタンの確認画面に出す料金。"""
    return {
        "unit_price": services.sync_unit_price(),
        "non_owner_unit_price": services.sync_unit_price(app_owner=False),
    }


def tweets_page(request):
    account = XAccount.objects.active()
    return render(
        request,
        "core/tweets.html",
        {
            "nav": "tweets",
            "tweets": Post.objects.own_tweets(account) if account else [],
            **_sync_prices(),
        },
    )


def replies_page(request):
    account = XAccount.objects.active()
    return render(
        request,
        "core/replies.html",
        {
            "nav": "replies",
            "threads": Post.objects.reply_threads(account) if account else [],
            **_sync_prices(),
        },
    )


def _tweets_html(request, account):
    return render_to_string(
        "core/_tweet_list.html", {"tweets": Post.objects.own_tweets(account)}, request
    )


def _replies_html(request, account):
    return render_to_string(
        "core/_reply_list.html",
        {"threads": Post.objects.reply_threads(account)},
        request,
    )


# ---------- API ----------


def _validated_text(request, images):
    return services.validate_text(request.POST.get("text", ""), has_images=bool(images))


@require_POST
@api_view
def sync_tweets(request, account):
    services.sync_own_posts(account)
    return JsonResponse({"html": _tweets_html(request, account)})


@require_POST
@api_view
def sync_replies(request, account):
    found = services.sync_replies(account)
    return JsonResponse({"html": _replies_html(request, account), "found": found})


@require_POST
@api_view
def create_tweet(request, account):
    images = request.FILES.getlist("images")
    services.validate_images(images)
    text = _validated_text(request, images)
    services.post_tweet(account, text, images)
    return JsonResponse({"html": _tweets_html(request, account)})


@require_POST
@api_view
def create_reply(request, account):
    reply_to = request.POST.get("reply_to", "")
    # 返信できるのは、自分のツイートへ来た返信だけ
    target = get_object_or_404(Post.objects.replies_to_me(account), x_id=reply_to)
    images = request.FILES.getlist("images")
    services.validate_images(images)
    text = _validated_text(request, images)
    services.post_tweet(account, text, images, reply_to=target.x_id)
    return JsonResponse({"html": _replies_html(request, account)})


# ---------- X アカウントの連携 ----------


def _expected_origin():
    """連携の戻り先として登録しているアドレス (例: http://127.0.0.1:8000)。"""
    parsed = urlparse(settings.X_REDIRECT_URI)
    return f"{parsed.scheme}://{parsed.netloc}"


def x_connect(request):
    if not x_api.is_configured():
        request.session["flash"] = (
            ".env に X_CLIENT_ID と X_CLIENT_SECRET を設定してください。"
        )
        return redirect("core:tweets")
    # Xから戻ってくるのは登録したアドレス。別のアドレス (localhost など) で始めると、
    # ブラウザの記録が引き継がれず、戻ったときに必ず失敗する。始める前に止める。
    if request.get_host() != urlparse(settings.X_REDIRECT_URI).netloc:
        request.session["flash"] = (
            f"{_expected_origin()}/ で開き直してから、もう一度連携してください "
            f"(いまは {request.get_host()} で開いています)。"
        )
        return redirect("core:tweets")
    verifier, challenge = x_api.new_pkce()
    state = secrets.token_urlsafe(32)
    request.session["x_oauth"] = {"state": state, "verifier": verifier}
    return redirect(x_api.build_authorize_url(state, challenge))


def _callback_failed(request, reason, message):
    """失敗の理由をログに残し (秘密情報は含めない)、画面には原因に合った案内を出す。"""
    logger.warning(
        "X connect callback failed: %s (host=%s)", reason, request.get_host()
    )
    request.session["flash"] = message
    return redirect("core:tweets")


def x_callback(request):
    saved = request.session.pop("x_oauth", None)
    if request.GET.get("error"):
        return _callback_failed(
            request,
            f"x returned error={request.GET.get('error')}",
            "Xとの連携がキャンセルされました。",
        )
    if not saved:
        return _callback_failed(
            request,
            "no pending connect in session",
            f"連携の開始記録が見つかりませんでした。{_expected_origin()}/ を1つのタブで開き、"
            "歯車の「Xアカウントを追加」からやり直してください (戻るボタンや再読み込みは使わないでください)。",
        )
    if not request.GET.get("code"):
        return _callback_failed(
            request,
            "no code in callback",
            "Xから認可コードが届きませんでした。もう一度お試しください。",
        )
    if not secrets.compare_digest(saved["state"], request.GET.get("state", "")):
        return _callback_failed(
            request,
            "state mismatch",
            "別の連携操作と混ざりました。連携の画面を開いたタブを1つだけにして、もう一度お試しください。",
        )

    try:
        token = x_api.exchange_code(request.GET["code"], saved["verifier"])
        me = x_api.get_me(token["access_token"])
    except x_api.XApiError as exc:
        request.session["flash"] = exc.message
        return redirect("core:tweets")

    account = XAccount.connect(me, token)
    request.session["flash"] = f"@{account.username} を連携しました。"
    return redirect("core:tweets")


@require_POST
def x_switch(request, pk):
    """切り替えたあとは、JS が今の画面を読み込み直す。"""
    get_object_or_404(XAccount, pk=pk).activate()
    return JsonResponse({})


@require_POST
def x_disconnect(request, pk):
    """削除したあとは、JS が今の画面を読み込み直す (メッセージはそこで出る)。"""
    account = get_object_or_404(XAccount, pk=pk)
    account.disconnect()
    request.session["flash"] = f"@{account.username} の連携を削除しました。"
    return JsonResponse({})
