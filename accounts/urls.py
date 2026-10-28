from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.login_page, name="login"),
    path("api/login/", views.login_api, name="login_api"),
    path("2fa/", views.two_factor_page, name="two_factor"),
    path("api/2fa/", views.two_factor_api, name="two_factor_api"),
    path("logout/", views.logout_view, name="logout"),
]
