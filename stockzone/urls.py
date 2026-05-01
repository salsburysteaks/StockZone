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
from core.views import dashboard, signup_view, login_view, logout_view, make_picks, my_picks, portfolio, buy_stock, sell_stock, leaderboard

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", dashboard, name="dashboard"),
    path("signup/", signup_view, name="signup"),
    path("login/", login_view, name="login"),
    path("logout/", logout_view, name="logout"),
    path("picks/make/", make_picks, name="make_picks"),
    path("picks/today/", my_picks, name="my_picks"),
    path("portfolio/", portfolio, name="portfolio"),
    path("portfolio/buy/", buy_stock, name="buy_stock"),
    path("portfolio/sell/", sell_stock, name="sell_stock"),
    path("leaderboard/", leaderboard, name="leaderboard"),
]
