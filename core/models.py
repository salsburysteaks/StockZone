from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from decimal import Decimal
import datetime


class Stock(models.Model):
    ticker = models.CharField(max_length=10)
    sector = models.CharField(max_length=100)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    momentum = models.DecimalField(max_digits=5, decimal_places=2)
    notes = models.TextField(blank=True)
    created_date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.ticker


class Portfolio(models.Model):
    ticker = models.CharField(max_length=10)
    shares = models.DecimalField(max_digits=10, decimal_places=4)
    buy_price = models.DecimalField(max_digits=10, decimal_places=2)
    purchase_date = models.DateField()

    def __str__(self):
        return f"{self.ticker} ({self.shares} shares)"


class DailyPick(models.Model):
    DIRECTION_CHOICES = [("UP", "Up"), ("DOWN", "Down")]
    RESULT_CHOICES = [("WIN", "Win"), ("LOSS", "Loss"), ("PENDING", "Pending")]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="daily_picks")
    ticker = models.CharField(max_length=10)
    sector = models.CharField(max_length=100)
    direction = models.CharField(max_length=4, choices=DIRECTION_CHOICES)
    picked_at = models.DateTimeField(auto_now_add=True)
    result = models.CharField(max_length=7, choices=RESULT_CHOICES, null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.user} — {self.ticker} {self.direction}"


class PaperPortfolio(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="paper_portfolio")
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=10000)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user} — ${self.balance}"


class PaperHolding(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="paper_holdings")
    ticker = models.CharField(max_length=10)
    shares = models.DecimalField(max_digits=10, decimal_places=4)
    buy_price = models.DecimalField(max_digits=10, decimal_places=2)
    bought_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user} — {self.ticker} ({self.shares} shares)"


class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    current_streak = models.IntegerField(default=0)
    longest_streak = models.IntegerField(default=0)
    total_picks = models.IntegerField(default=0)
    total_wins = models.IntegerField(default=0)
    last_pick_date = models.DateField(null=True, blank=True)
    has_completed_onboarding = models.BooleanField(default=False)
    has_seen_tour = models.BooleanField(default=False)
    display_name = models.CharField(max_length=50, blank=True)
    bio = models.TextField(max_length=150, blank=True)

    @property
    def win_rate(self):
        if self.total_picks == 0:
            return 0.0
        return round(self.total_wins / self.total_picks * 100, 1)

    def __str__(self):
        return f"{self.user.username} profile"


class Parlay(models.Model):
    RESULT_CHOICES = [("PENDING", "Pending"), ("WIN", "Win"), ("LOSS", "Loss")]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="parlays")
    created_at = models.DateTimeField(auto_now_add=True)
    result = models.CharField(max_length=7, choices=RESULT_CHOICES, default="PENDING")
    payout_multiplier = models.DecimalField(max_digits=8, decimal_places=4, default=1.0)
    wager = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    payout = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    def calculate_multiplier(self):
        return round(1.5 ** self.legs.count(), 4)

    @property
    def leg_count(self):
        return self.legs.count()

    def __str__(self):
        return f"{self.user} parlay — {self.leg_count} legs"


class ParlayLeg(models.Model):
    DIRECTION_CHOICES = [("UP", "Up"), ("DOWN", "Down")]
    RESULT_CHOICES = [("WIN", "Win"), ("LOSS", "Loss"), ("PENDING", "Pending")]

    parlay = models.ForeignKey(Parlay, on_delete=models.CASCADE, related_name="legs")
    ticker = models.CharField(max_length=10)
    sector = models.CharField(max_length=100, blank=True)
    direction = models.CharField(max_length=4, choices=DIRECTION_CHOICES)
    price_at_pick = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    odds = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("1.50"))
    result = models.CharField(max_length=7, choices=RESULT_CHOICES, default="PENDING")

    def __str__(self):
        return f"{self.parlay} — {self.ticker} {self.direction}"


class FutureBet(models.Model):
    TIMEFRAME_CHOICES = [
        ("3D", "3 Days"),
        ("1W", "1 Week"),
        ("2W", "2 Weeks"),
        ("1M", "1 Month"),
    ]
    DIRECTION_CHOICES = [("UP", "Up"), ("DOWN", "Down")]
    RESULT_CHOICES = [("WIN", "Win"), ("LOSS", "Loss"), ("PENDING", "Pending")]

    TIMEFRAME_DAYS = {"3D": 3, "1W": 7, "2W": 14, "1M": 30}

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="future_bets")
    ticker = models.CharField(max_length=10)
    sector = models.CharField(max_length=100, blank=True)
    direction = models.CharField(max_length=4, choices=DIRECTION_CHOICES)
    timeframe = models.CharField(max_length=2, choices=TIMEFRAME_CHOICES)
    price_at_pick = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    wager = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    daily_odds_multiplier = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal("2.00"))
    result = models.CharField(max_length=7, choices=RESULT_CHOICES, default="PENDING")
    payout = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    placed_at = models.DateTimeField(auto_now_add=True)
    resolves_at = models.DateField()
    resolved_at = models.DateTimeField(null=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.pk and not self.resolves_at:
            days = self.TIMEFRAME_DAYS.get(self.timeframe, 7)
            self.resolves_at = (timezone.now() + datetime.timedelta(days=days)).date()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user} — {self.ticker} {self.direction} ({self.get_timeframe_display()})"


class Follow(models.Model):
    follower  = models.ForeignKey(User, on_delete=models.CASCADE, related_name="following")
    following = models.ForeignKey(User, on_delete=models.CASCADE, related_name="followers")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("follower", "following")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.follower} -> {self.following}"


class BullishPick(models.Model):
    DIRECTION_CHOICES = [("UP", "Up"), ("DOWN", "Down")]

    ticker       = models.CharField(max_length=10)
    company_name = models.CharField(max_length=100)
    sector       = models.CharField(max_length=100, blank=True)
    direction    = models.CharField(max_length=4, choices=DIRECTION_CHOICES)
    reasoning    = models.TextField()
    price        = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    momentum     = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    generated_at = models.DateTimeField(auto_now_add=True)
    date         = models.DateField(unique=True)

    class Meta:
        ordering = ["-date"]

    def __str__(self):
        return f"{self.date} — {self.ticker} {self.direction}"


class PortfolioSnapshot(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="portfolio_snapshots")
    date = models.DateField()
    total_value = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        unique_together = ("user", "date")
        ordering = ["date"]

    def __str__(self):
        return f"{self.user} — {self.date}: ${self.total_value}"


class Notification(models.Model):
    TYPE_CHOICES = [
        ("pick_resolved", "Pick Resolved"),
        ("parlay_resolved", "Parlay Resolved"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notifications")
    message = models.TextField()
    notification_type = models.CharField(max_length=30, choices=TYPE_CHOICES)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user} — {self.notification_type}: {self.message[:60]}"
