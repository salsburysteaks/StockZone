from django.db import models
from django.contrib.auth.models import User


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
