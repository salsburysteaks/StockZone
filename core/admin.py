from django.contrib import admin
from .models import Stock, Portfolio, DailyPick, PaperPortfolio, PaperHolding, UserProfile, Parlay, ParlayLeg, FutureBet, BullishPick


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


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'current_streak', 'longest_streak', 'total_picks', 'total_wins', 'win_rate_display')
    search_fields = ('user__username',)

    def win_rate_display(self, obj):
        return f"{obj.win_rate}%"
    win_rate_display.short_description = "Win Rate"


@admin.register(Parlay)
class ParlayAdmin(admin.ModelAdmin):
    list_display = ('user', 'result', 'payout_multiplier', 'leg_count', 'created_at')
    list_filter = ('result',)
    search_fields = ('user__username',)

    def leg_count(self, obj):
        return obj.leg_count
    leg_count.short_description = "Legs"


@admin.register(ParlayLeg)
class ParlayLegAdmin(admin.ModelAdmin):
    list_display = ('parlay', 'ticker', 'direction', 'price_at_pick', 'result')
    list_filter = ('direction', 'result')
    search_fields = ('ticker',)


@admin.register(FutureBet)
class FutureBetAdmin(admin.ModelAdmin):
    list_display = ('user', 'ticker', 'direction', 'timeframe', 'wager', 'payout', 'result', 'placed_at', 'resolves_at')
    list_filter = ('direction', 'timeframe', 'result')
    search_fields = ('user__username', 'ticker')


@admin.register(BullishPick)
class BullishPickAdmin(admin.ModelAdmin):
    list_display = ('date', 'ticker', 'company_name', 'direction', 'price', 'momentum', 'generated_at')
    list_filter = ('direction',)
    search_fields = ('ticker', 'company_name')
    readonly_fields = ('generated_at',)
