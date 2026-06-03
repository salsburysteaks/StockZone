"""
URL configuration for stockzone project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.urls import path
from django.views.generic import RedirectView
from core.views import (
    landing, dashboard, signup_view, login_view, logout_view,
    make_picks, my_picks,
    portfolio, buy_stock, sell_stock,
    leaderboard,
    build_parlay, my_parlays,
    place_future_bet, my_future_bets,
    picks_leaderboard,
    user_profile,
    resolve_picks_view,
    how_to_play,
    glossary,
    stock_analyzer,
    stock_news,
    notifications_json, mark_notifications_read,
    onboarding,
    assistant_chat,
    friends_list, follow_user, user_search, friend_profile,
    stock_prices_json,
    edit_profile,
    share_parlay, share_streak,
    stock_detail, stock_chart_json,
)

urlpatterns = [
    path("admin/resolve/", resolve_picks_view, name="resolve_picks"),
    path("admin/", admin.site.urls),
    path("onboarding/", onboarding, name="onboarding"),
    path("assistant/", assistant_chat, name="assistant_chat"),
    path("", landing, name="landing"),
    path("dashboard/", dashboard, name="dashboard"),
    path("signup/", signup_view, name="signup"),
    path("login/", login_view, name="login"),
    path("logout/", logout_view, name="logout"),
    path("picks/make/", RedirectView.as_view(pattern_name="build_parlay", permanent=False), name="make_picks"),
    path("picks/today/", my_picks, name="my_picks"),
    path("portfolio/", portfolio, name="portfolio"),
    path("portfolio/buy/", buy_stock, name="buy_stock"),
    path("portfolio/sell/", sell_stock, name="sell_stock"),
    path("leaderboard/", leaderboard, name="leaderboard"),
    path("leaderboard/picks/", picks_leaderboard, name="picks_leaderboard"),
    path("parlay/build/", build_parlay, name="build_parlay"),
    path("parlay/mine/", my_parlays, name="my_parlays"),
    path("future-bets/place/", place_future_bet, name="place_future_bet"),
    path("future-bets/mine/", my_future_bets, name="my_future_bets"),
    path("profile/", user_profile, name="my_profile"),
    path("profile/edit/", edit_profile, name="edit_profile"),
    path("profile/<str:username>/", user_profile, name="user_profile"),
    path("how-to-play/", how_to_play, name="how_to_play"),
    path("glossary/", glossary, name="glossary"),
    path("analyzer/", stock_analyzer, name="stock_analyzer"),
    path("news/<str:ticker>/", stock_news, name="stock_news"),
    path("notifications/", notifications_json, name="notifications"),
    path("notifications/read/", mark_notifications_read, name="mark_notifications_read"),
    path("dashboard/prices/", stock_prices_json, name="stock_prices_json"),
    path("stock/<str:ticker>/", stock_detail, name="stock_detail"),
    path("stock/<str:ticker>/chart/", stock_chart_json, name="stock_chart_json"),
    path("share/parlay/<int:parlay_id>/", share_parlay, name="share_parlay"),
    path("share/streak/<str:username>/", share_streak, name="share_streak"),
    path("friends/", friends_list, name="friends_list"),
    path("friends/follow/<str:username>/", follow_user, name="follow_user"),
    path("friends/search/", user_search, name="user_search"),
    path("friends/profile/<str:username>/", friend_profile, name="friend_profile"),
]
