from django.urls import path

from . import dev_views, views

app_name = "core"

urlpatterns = [
    path("", views.tweets_page, name="tweets"),
    path("replies/", views.replies_page, name="replies"),
    path("api/tweets/", views.create_tweet, name="create_tweet"),
    path("api/tweets/sync/", views.sync_tweets, name="sync_tweets"),
    path("api/replies/", views.create_reply, name="create_reply"),
    path("api/replies/sync/", views.sync_replies, name="sync_replies"),
    path("x/connect/", views.x_connect, name="x_connect"),
    path("x/callback/", views.x_callback, name="x_callback"),
    path("x/<int:pk>/switch/", views.x_switch, name="x_switch"),
    path("x/<int:pk>/disconnect/", views.x_disconnect, name="x_disconnect"),
    # 開発用のデザイン確認ページ (DEBUG=False では 404)
    path("dev/", dev_views.index, name="dev_index"),
    path("dev/two-factor-setup/", dev_views.two_factor_setup, name="dev_two_factor_setup"),
    path("dev/x-connect/", dev_views.x_connect, name="dev_x_connect"),
]
