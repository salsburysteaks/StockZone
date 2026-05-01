from django.shortcuts import render, redirect
from django.contrib.auth import login, logout
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from decimal import Decimal, InvalidOperation
from collections import defaultdict
import yfinance as yf
from .models import PaperPortfolio, PaperHolding, DailyPick
from .stock_data import get_top_stocks_by_sector, COMPANY_NAMES


@login_required
def dashboard(request):
    stocks = get_top_stocks_by_sector()
    by_sector = defaultdict(list)
    for stock in stocks:
        by_sector[stock["sector"]].append(stock)
    spotlight = max(stocks, key=lambda s: s["momentum"]) if stocks else None
    return render(request, "core/dashboard.html", {
        "sectors": dict(by_sector),
        "all_stocks": stocks,
        "spotlight": spotlight,
    })


def signup_view(request):
    if request.method == "POST":
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            PaperPortfolio.objects.create(user=user, balance=10000)
            login(request, user)
            return redirect("dashboard")
    else:
        form = UserCreationForm()
    return render(request, "core/signup.html", {"form": form})


def login_view(request):
    if request.method == "POST":
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            return redirect("dashboard")
    else:
        form = AuthenticationForm()
    return render(request, "core/login.html", {"form": form})


def logout_view(request):
    logout(request)
    return redirect("login")


@login_required
def make_picks(request):
    today = timezone.localdate()
    already_picked = DailyPick.objects.filter(user=request.user, picked_at__date=today).exists()
    if already_picked:
        return redirect("my_picks")

    stocks = get_top_stocks_by_sector()

    if request.method == "POST":
        valid_tickers = {s["ticker"]: s for s in stocks}
        picks_to_create = []
        for key, direction in request.POST.items():
            if key.startswith("pick_") and direction in ("UP", "DOWN"):
                ticker = key[len("pick_"):]
                if ticker in valid_tickers:
                    stock = valid_tickers[ticker]
                    picks_to_create.append(DailyPick(
                        user=request.user,
                        ticker=ticker,
                        sector=stock["sector"],
                        direction=direction,
                        result="PENDING",
                    ))
        DailyPick.objects.bulk_create(picks_to_create)
        return redirect("my_picks")

    by_sector = defaultdict(list)
    for stock in stocks:
        by_sector[stock["sector"]].append(stock)
    return render(request, "core/make_picks.html", {"sectors": dict(by_sector)})


@login_required
def my_picks(request):
    today = timezone.localdate()
    picks = DailyPick.objects.filter(user=request.user, picked_at__date=today).order_by("sector", "ticker")
    by_sector = defaultdict(list)
    for pick in picks:
        pick.company_name = COMPANY_NAMES.get(pick.ticker, pick.ticker)
        by_sector[pick.sector].append(pick)
    wins = picks.filter(result="WIN").count()
    losses = picks.filter(result="LOSS").count()
    pending = picks.filter(result="PENDING").count()
    return render(request, "core/my_picks.html", {
        "sectors": dict(by_sector),
        "wins": wins,
        "losses": losses,
        "pending": pending,
        "total": picks.count(),
    })


def _fetch_prices(tickers):
    """Return {ticker: float price} for a list of tickers."""
    if not tickers:
        return {}
    raw = yf.download(tickers, period="2d", auto_adjust=True, progress=False)["Close"]
    # yfinance returns a Series when given a bare string, DataFrame for a list.
    # Normalise to DataFrame so column lookup works uniformly for all cases.
    if raw.ndim == 1:
        raw = raw.to_frame(name=tickers[0])
    prices = {}
    for t in tickers:
        try:
            prices[t] = float(raw[t].dropna().iloc[-1])
        except Exception:
            prices[t] = None
    return prices


@login_required
def portfolio(request):
    paper, _ = PaperPortfolio.objects.get_or_create(user=request.user, defaults={"balance": Decimal("10000")})
    holdings = list(PaperHolding.objects.filter(user=request.user).order_by("ticker"))

    tickers = list({h.ticker for h in holdings})
    prices = _fetch_prices(tickers)

    enriched = []
    total_holdings_value = Decimal("0")
    for h in holdings:
        current_price = prices.get(h.ticker)
        if current_price is not None:
            current_price = Decimal(str(round(current_price, 2)))
            gain_loss = (current_price - h.buy_price) * h.shares
            gain_loss_pct = round((current_price - h.buy_price) / h.buy_price * 100, 2)
            holding_value = current_price * h.shares
            total_holdings_value += holding_value
        else:
            gain_loss = gain_loss_pct = holding_value = None
        enriched.append({
            "holding": h,
            "current_price": current_price,
            "gain_loss": gain_loss,
            "gain_loss_pct": gain_loss_pct,
            "holding_value": holding_value,
        })

    return render(request, "core/portfolio.html", {
        "paper": paper,
        "holdings": enriched,
        "total_holdings_value": total_holdings_value,
        "total_value": paper.balance + total_holdings_value,
    })


@login_required
def leaderboard(request):
    portfolios = PaperPortfolio.objects.select_related("user").all()
    all_holdings = PaperHolding.objects.all()

    holdings_by_user = defaultdict(list)
    for h in all_holdings:
        holdings_by_user[h.user_id].append(h)

    all_tickers = list({h.ticker for h in all_holdings})
    prices = _fetch_prices(all_tickers)

    STARTING_BALANCE = Decimal("10000")
    rows = []
    for paper in portfolios:
        holdings_value = Decimal("0")
        for h in holdings_by_user.get(paper.user_id, []):
            price = prices.get(h.ticker)
            if price is not None:
                holdings_value += Decimal(str(round(price, 2))) * h.shares
        total_value = paper.balance + holdings_value
        rows.append({
            "username": paper.user.username,
            "balance": paper.balance,
            "holdings_value": holdings_value,
            "total_value": total_value,
            "gain_loss": total_value - STARTING_BALANCE,
        })

    rows.sort(key=lambda r: r["total_value"], reverse=True)
    for i, row in enumerate(rows, 1):
        row["rank"] = i

    return render(request, "core/leaderboard.html", {"rows": rows})


@login_required
def buy_stock(request):
    if request.method != "POST":
        return redirect("portfolio")

    ticker = request.POST.get("ticker", "").upper().strip()
    shares_raw = request.POST.get("shares", "").strip()

    try:
        shares = Decimal(shares_raw)
        if shares <= 0:
            raise InvalidOperation
    except (InvalidOperation, Exception):
        messages.error(request, "Enter a valid positive number of shares.")
        return redirect("portfolio")

    if not ticker:
        messages.error(request, "Enter a ticker symbol.")
        return redirect("portfolio")

    prices = _fetch_prices([ticker])
    current_price = prices.get(ticker)
    if current_price is None:
        messages.error(request, f"Could not fetch a price for '{ticker}'. Check the ticker and try again.")
        return redirect("portfolio")

    current_price = Decimal(str(round(current_price, 2)))
    cost = (current_price * shares).quantize(Decimal("0.01"))

    paper, _ = PaperPortfolio.objects.get_or_create(user=request.user, defaults={"balance": Decimal("10000")})
    if cost > paper.balance:
        messages.error(request, f"Insufficient balance. Cost: ${cost:,.2f} — Available: ${paper.balance:,.2f}")
        return redirect("portfolio")

    paper.balance -= cost
    paper.save()
    PaperHolding.objects.create(user=request.user, ticker=ticker, shares=shares, buy_price=current_price)
    messages.success(request, f"Bought {shares} share(s) of {ticker} at ${current_price} each.")
    return redirect("portfolio")


@login_required
def sell_stock(request):
    if request.method != "POST":
        return redirect("portfolio")

    holding_id = request.POST.get("holding_id", "").strip()
    shares_raw = request.POST.get("shares", "").strip()

    try:
        holding = PaperHolding.objects.get(id=holding_id, user=request.user)
    except PaperHolding.DoesNotExist:
        messages.error(request, "Holding not found.")
        return redirect("portfolio")

    try:
        shares = Decimal(shares_raw)
        if shares <= 0:
            raise InvalidOperation
    except (InvalidOperation, Exception):
        messages.error(request, "Enter a valid positive number of shares.")
        return redirect("portfolio")

    if shares > holding.shares:
        messages.error(request, f"You only own {holding.shares} share(s) of {holding.ticker}.")
        return redirect("portfolio")

    prices = _fetch_prices([holding.ticker])
    current_price = prices.get(holding.ticker)
    if current_price is None:
        messages.error(request, f"Could not fetch a price for '{holding.ticker}'. Try again.")
        return redirect("portfolio")

    current_price = Decimal(str(round(current_price, 2)))
    proceeds = (current_price * shares).quantize(Decimal("0.01"))

    paper, _ = PaperPortfolio.objects.get_or_create(user=request.user, defaults={"balance": Decimal("10000")})
    paper.balance += proceeds
    paper.save()

    if shares == holding.shares:
        holding.delete()
    else:
        holding.shares -= shares
        holding.save()

    messages.success(request, f"Sold {shares} share(s) of {holding.ticker} at ${current_price} each. Received ${proceeds:,.2f}.")
    return redirect("portfolio")
