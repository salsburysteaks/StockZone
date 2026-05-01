from django.contrib import admin
from .models import Stock, Portfolio, DailyPick, PaperPortfolio, PaperHolding


@admin.register(Stock)
class StockAdmin(admin.ModelAdmin):
    list_display = ('ticker', 'sector', 'price', 'momentum', 'created_date')
    search_fields = ('ticker', 'sector')


@admin.register(Portfolio)
class PortfolioAdmin(admin.ModelAdmin):
    list_display = ('ticker', 'shares', 'buy_price', 'purchase_date')
    search_fields = ('ticker',)


@admin.register(DailyPick)
class DailyPickAdmin(admin.ModelAdmin):
    list_display = ('user', 'ticker', 'sector', 'direction', 'result', 'picked_at', 'resolved_at')
    search_fields = ('ticker', 'sector')
    list_filter = ('direction', 'result')


@admin.register(PaperPortfolio)
class PaperPortfolioAdmin(admin.ModelAdmin):
    list_display = ('user', 'balance', 'updated_at')
    search_fields = ('user__username',)


@admin.register(PaperHolding)
class PaperHoldingAdmin(admin.ModelAdmin):
    list_display = ('user', 'ticker', 'shares', 'buy_price', 'bought_at')
    search_fields = ('user__username', 'ticker')
