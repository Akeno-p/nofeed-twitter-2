from accounts.middleware import SESSION_KEY

from . import services, x_api
from .models import XAccount


def x_account(request):
    """全ページ共通: 連携中のXアカウントと、メッセージ (1回だけ表示)。"""
    if not request.user.is_authenticated or not request.session.get(SESSION_KEY):
        return {}
    accounts = list(XAccount.objects.all())
    return {
        "x_accounts": accounts,
        "x_account": next((a for a in accounts if a.is_active), None),
        "x_configured": x_api.is_configured(),
        "flash": request.session.pop("flash", None),
        "tweet_max_length": 140,
        "link_post_price": services.link_post_price(),
        "link_pattern": services.LINK_PATTERN,
    }
