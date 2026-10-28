# レビューした
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import reverse

SESSION_KEY = "two_factor_verified"


class TwoFactorRequiredMiddleware:
    """全ページを保護する。

    - ログインしていなければログイン画面へ
    - ログイン済みでも2段階認証を通っていなければ2段階認証画面へ
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.login_path = reverse("accounts:login")
        self.login_api_path = reverse("accounts:login_api")
        self.two_factor_path = reverse("accounts:two_factor")
        self.two_factor_api_path = reverse("accounts:two_factor_api")
        self.logout_path = reverse("accounts:logout")

    def __call__(self, request):
        path = request.path
        if path.startswith("/static/"):
            return self.get_response(request)

        if not request.user.is_authenticated:
            if path in (self.login_path, self.login_api_path, self.logout_path):
                return self.get_response(request)
            return self._deny(request, self.login_path)

        if not request.session.get(SESSION_KEY) and path not in (
            self.login_path,
            self.login_api_path,
            self.two_factor_path,
            self.two_factor_api_path,
            self.logout_path,
        ):
            return self._deny(request, self.two_factor_path)

        return self.get_response(request)

    @staticmethod
    def _deny(request, redirect_to):
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse(
                {"error": "ログインが必要です。", "redirect": redirect_to},
                status=403,
            )
        return redirect(redirect_to)
