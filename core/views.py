from django.shortcuts import render, redirect
from django.contrib.auth import login, logout
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.utils import timezone
from decimal import Decimal, InvalidOperation
from collections import defaultdict
import datetime
import yfinance as yf
from .models import PaperPortfolio, PaperHolding, DailyPick, UserProfile, Parlay, ParlayLeg, FutureBet, Notification
from .stock_data import get_top_stocks_by_sector, COMPANY_NAMES, calculate_future_odds


def landing(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    return render(request, "core/landing.html")


def how_to_play(request):
    return render(request, "core/how_to_play.html")


@login_required
def dashboard(request):
    stocks = get_top_stocks_by_sector()
    by_sector = defaultdict(list)
    for stock in stocks:
        by_sector[stock["sector"]].append(stock)
    spotlight = max(stocks, key=lambda s: s["momentum"]) if stocks else None
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    return render(request, "core/dashboard.html", {
        "sectors": dict(by_sector),
        "all_stocks": stocks,
        "spotlight": spotlight,
        "ticker_stocks": stocks,
        "user_profile": profile,
    })


def signup_view(request):
    if request.method == "POST":
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            PaperPortfolio.objects.create(user=user, balance=10000)
            UserProfile.objects.create(user=user)
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


def _stock_odds(momentum):
    """Per-pick multiplier based on absolute momentum magnitude."""
    a = abs(float(momentum))
    if a > 50:
        return round(max(1.1, 1.3 - (a - 50) * 0.004), 2)
    elif a >= 20:
        return round(1.4 + (50 - a) * (0.2 / 30), 2)
    else:
        return round(1.7 + (20 - a) * (0.5 / 20), 2)


@login_required
def make_picks(request):
    today = timezone.localdate()
    stocks = get_top_stocks_by_sector()
    for stock in stocks:
        stock["odds"] = _stock_odds(stock["momentum"])

    portfolio, _ = PaperPortfolio.objects.get_or_create(
        user=request.user, defaults={"balance": Decimal("10000")}
    )

    if request.method == "POST":
        valid_tickers = {s["ticker"]: s for s in stocks}
        picks_by_ticker = {}
        for key, direction in request.POST.items():
            if key.startswith("pick_") and direction in ("UP", "DOWN"):
                ticker = key[len("pick_"):]
                if ticker in valid_tickers:
                    stock = valid_tickers[ticker]
                    picks_by_ticker[ticker] = DailyPick(
                        user=request.user,
                        ticker=ticker,
                        sector=stock["sector"],
                        direction=direction,
                        result="PENDING",
                    )
        if picks_by_ticker:
            try:
                wager = Decimal(request.POST.get("wager", "0") or "0")
                wager = max(Decimal("0"), min(wager, portfolio.balance))
            except InvalidOperation:
                wager = Decimal("0")
            request.session["daily_picks_wager"] = str(wager)
            DailyPick.objects.filter(user=request.user, picked_at__date=today).delete()
            DailyPick.objects.bulk_create(picks_by_ticker.values())

    by_sector = defaultdict(list)
    for stock in stocks:
        by_sector[stock["sector"]].append(stock)
    return render(request, "core/make_picks.html", {
        "sectors": dict(by_sector),
        "ticker_stocks": stocks,
        "balance": portfolio.balance,
    })


@login_required
def my_picks(request):
    all_picks = DailyPick.objects.filter(user=request.user).order_by("-picked_at")

    total = all_picks.count()
    wins = all_picks.filter(result="WIN").count()
    losses = all_picks.filter(result="LOSS").count()
    win_rate = round(wins / total * 100, 1) if total > 0 else 0

    streak = 0
    for pick in all_picks:
        if pick.result == "PENDING":
            continue
        if pick.result == "WIN":
            streak += 1
        else:
            break

    date_groups = []
    current_date = None
    current_group = []
    for pick in all_picks:
        pick.company_name = COMPANY_NAMES.get(pick.ticker, pick.ticker)
        pick_date = pick.picked_at.date()
        if pick_date != current_date:
            if current_group:
                date_groups.append({
                    "date": current_date,
                    "picks": current_group,
                    "total": len(current_group),
                    "wins": sum(1 for p in current_group if p.result == "WIN"),
                    "losses": sum(1 for p in current_group if p.result == "LOSS"),
                    "pending": sum(1 for p in current_group if p.result == "PENDING"),
                })
            current_date = pick_date
            current_group = [pick]
        else:
            current_group.append(pick)
    if current_group:
        date_groups.append({
            "date": current_date,
            "picks": current_group,
            "total": len(current_group),
            "wins": sum(1 for p in current_group if p.result == "WIN"),
            "losses": sum(1 for p in current_group if p.result == "LOSS"),
            "pending": sum(1 for p in current_group if p.result == "PENDING"),
        })

    return render(request, "core/my_picks.html", {
        "date_groups": date_groups,
        "total": total,
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "streak": streak,
        "ticker_stocks": get_top_stocks_by_sector(),
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
        "ticker_stocks": get_top_stocks_by_sector(),
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

    return render(request, "core/leaderboard.html", {"rows": rows, "ticker_stocks": get_top_stocks_by_sector()})


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


@login_required
def build_parlay(request):
    stocks = get_top_stocks_by_sector()
    by_sector = defaultdict(list)
    for stock in stocks:
        by_sector[stock["sector"]].append(stock)

    paper, _ = PaperPortfolio.objects.get_or_create(
        user=request.user, defaults={"balance": Decimal("10000")}
    )

    ctx = {"sectors": dict(by_sector), "ticker_stocks": stocks, "paper": paper}

    if request.method == "POST":
        valid_tickers = {s["ticker"]: s for s in stocks}
        legs = []
        for key, direction in request.POST.items():
            if key.startswith("leg_") and direction in ("UP", "DOWN"):
                ticker = key[len("leg_"):]
                if ticker in valid_tickers:
                    legs.append((ticker, valid_tickers[ticker], direction))

        if len(legs) < 2:
            messages.error(request, "Select at least 2 legs to build a parlay.")
            return render(request, "core/build_parlay.html", ctx)
        if len(legs) > 5:
            messages.error(request, "A parlay can have at most 5 legs.")
            return render(request, "core/build_parlay.html", ctx)

        try:
            wager = Decimal(request.POST.get("wager", "0")).quantize(Decimal("0.01"))
        except InvalidOperation:
            messages.error(request, "Invalid wager amount.")
            return render(request, "core/build_parlay.html", ctx)

        if wager <= 0:
            messages.error(request, "Wager must be greater than $0.")
            return render(request, "core/build_parlay.html", ctx)
        if wager > paper.balance:
            messages.error(request, f"Insufficient balance. You have ${paper.balance:,.2f}.")
            return render(request, "core/build_parlay.html", ctx)

        leg_tickers = [ticker for ticker, _, _ in legs]
        live_prices = _fetch_prices(leg_tickers)

        _DIFFICULTY_BONUS = {2: "1.0", 3: "1.25", 4: "1.6", 5: "2.2"}

        multiplier = Decimal("1")
        for ticker, stock, direction in legs:
            leg_odds = stock.get("odds_up" if direction == "UP" else "odds_down") or 1.5
            multiplier *= Decimal(str(leg_odds))
        bonus = Decimal(_DIFFICULTY_BONUS.get(len(legs), "1.0"))
        multiplier = (multiplier * bonus).quantize(Decimal("0.0001"))
        potential_payout = (wager * multiplier).quantize(Decimal("0.01"))

        parlay = Parlay.objects.create(
            user=request.user,
            payout_multiplier=multiplier,
            wager=wager,
        )
        for ticker, stock, direction in legs:
            raw_price = live_prices.get(ticker)
            price_at_pick = Decimal(str(round(raw_price, 2))) if raw_price else None
            leg_odds = stock.get("odds_up" if direction == "UP" else "odds_down") or 1.5
            ParlayLeg.objects.create(
                parlay=parlay,
                ticker=ticker,
                sector=stock["sector"],
                direction=direction,
                price_at_pick=price_at_pick,
                odds=Decimal(str(leg_odds)),
            )

        paper.balance -= wager
        paper.save()

        messages.success(request, f"Parlay locked! {len(legs)} legs · ${wager:,.2f} wagered · potential payout ${potential_payout:,.2f}")
        return redirect("my_parlays")

    return render(request, "core/build_parlay.html", ctx)


@login_required
def my_parlays(request):
    parlays = (
        Parlay.objects.filter(user=request.user)
        .prefetch_related("legs")
        .order_by("-created_at")
    )
    return render(request, "core/my_parlays.html", {"parlays": parlays, "ticker_stocks": get_top_stocks_by_sector()})


@login_required
def place_future_bet(request):
    stocks = get_top_stocks_by_sector()
    by_sector = defaultdict(list)
    for stock in stocks:
        by_sector[stock["sector"]].append(stock)

    paper, _ = PaperPortfolio.objects.get_or_create(user=request.user, defaults={"balance": Decimal("10000")})

    if request.method == "POST":
        ticker = request.POST.get("ticker", "").upper().strip()
        direction = request.POST.get("direction", "")
        timeframe = request.POST.get("timeframe", "")
        wager_raw = request.POST.get("wager", "").strip()

        ctx = {
            "sectors": dict(by_sector),
            "timeframe_choices": FutureBet.TIMEFRAME_CHOICES,
            "paper": paper,
            "ticker_stocks": stocks,
        }

        valid_tickers = {s["ticker"]: s for s in stocks}
        if ticker not in valid_tickers or direction not in ("UP", "DOWN") or timeframe not in FutureBet.TIMEFRAME_DAYS:
            messages.error(request, "Invalid bet — check ticker, direction, and timeframe.")
            return render(request, "core/place_future_bet.html", ctx)

        try:
            wager = Decimal(wager_raw).quantize(Decimal("0.01"))
            if wager <= 0:
                raise InvalidOperation
        except (InvalidOperation, Exception):
            messages.error(request, "Enter a valid positive wager amount.")
            return render(request, "core/place_future_bet.html", ctx)

        if wager > paper.balance:
            messages.error(request, f"Insufficient balance — wager ${wager:,.2f}, available ${paper.balance:,.2f}.")
            return render(request, "core/place_future_bet.html", ctx)

        stock = valid_tickers[ticker]
        prices = _fetch_prices([ticker])
        raw_price = prices.get(ticker)
        price_at_pick = Decimal(str(round(raw_price, 2))) if raw_price else None

        import datetime as dt
        days = FutureBet.TIMEFRAME_DAYS[timeframe]
        resolves_at = (timezone.now() + dt.timedelta(days=days)).date()

        realized_vol = stock.get("realized_vol", 1.0)
        odds_multiplier = Decimal(str(calculate_future_odds(realized_vol, timeframe)))

        paper.balance -= wager
        paper.save()

        FutureBet.objects.create(
            user=request.user,
            ticker=ticker,
            sector=stock["sector"],
            direction=direction,
            timeframe=timeframe,
            price_at_pick=price_at_pick,
            wager=wager,
            daily_odds_multiplier=odds_multiplier,
            resolves_at=resolves_at,
        )
        messages.success(request, f"Bet locked — ${wager:,.2f} on {ticker} {direction} ({dict(FutureBet.TIMEFRAME_CHOICES)[timeframe]}).")
        return redirect("my_future_bets")

    return render(request, "core/place_future_bet.html", {
        "sectors": dict(by_sector),
        "timeframe_choices": FutureBet.TIMEFRAME_CHOICES,
        "paper": paper,
        "ticker_stocks": stocks,
    })


@login_required
def my_future_bets(request):
    bets = FutureBet.objects.filter(user=request.user).order_by("-placed_at")
    return render(request, "core/my_future_bets.html", {"bets": bets, "ticker_stocks": get_top_stocks_by_sector()})


@login_required
def picks_leaderboard(request):
    profiles = UserProfile.objects.select_related("user").all()
    rows = []
    for profile in profiles:
        rows.append({
            "username": profile.user.username,
            "win_rate": profile.win_rate,
            "total_picks": profile.total_picks,
            "total_wins": profile.total_wins,
            "current_streak": profile.current_streak,
            "longest_streak": profile.longest_streak,
        })
    rows.sort(key=lambda r: (r["win_rate"], r["total_wins"]), reverse=True)
    for i, row in enumerate(rows, 1):
        row["rank"] = i
    return render(request, "core/picks_leaderboard.html", {"rows": rows, "ticker_stocks": get_top_stocks_by_sector()})


@staff_member_required
def resolve_picks_view(request):
    from .resolution import resolve_all
    lines = []
    picks, parlays, bets = resolve_all(log=lines.append)
    summary = "\n".join(lines)
    return render(request, "core/resolve_summary.html", {
        "summary": summary,
        "picks": picks,
        "parlays": parlays,
        "bets": bets,
        "ticker_stocks": get_top_stocks_by_sector(),
    })


@login_required
def user_profile(request, username=None):
    from django.contrib.auth.models import User as AuthUser
    from django.shortcuts import get_object_or_404

    if username:
        target_user = get_object_or_404(AuthUser, username=username)
    else:
        target_user = request.user

    profile, _ = UserProfile.objects.get_or_create(user=target_user)
    picks = DailyPick.objects.filter(user=target_user).order_by("-picked_at")
    parlays = Parlay.objects.filter(user=target_user).prefetch_related("legs").order_by("-created_at")
    future_bets = FutureBet.objects.filter(user=target_user).order_by("-placed_at")

    total_picks_all = picks.count()
    wins_all = picks.filter(result="WIN").count()
    losses_all = picks.filter(result="LOSS").count()
    pending_all = picks.filter(result="PENDING").count()

    # Group picks from the last 7 days by date
    cutoff = timezone.now().date() - datetime.timedelta(days=7)
    recent_qs = picks.filter(picked_at__date__gte=cutoff)
    recent_date_groups = []
    current_date = None
    current_group = []
    for pick in recent_qs:
        pick_date = pick.picked_at.date()
        if pick_date != current_date:
            if current_group:
                recent_date_groups.append({
                    "date": current_date,
                    "picks": current_group,
                    "wins": sum(1 for p in current_group if p.result == "WIN"),
                    "losses": sum(1 for p in current_group if p.result == "LOSS"),
                    "pending": sum(1 for p in current_group if p.result == "PENDING"),
                })
            current_date = pick_date
            current_group = [pick]
        else:
            current_group.append(pick)
    if current_group:
        recent_date_groups.append({
            "date": current_date,
            "picks": current_group,
            "wins": sum(1 for p in current_group if p.result == "WIN"),
            "losses": sum(1 for p in current_group if p.result == "LOSS"),
            "pending": sum(1 for p in current_group if p.result == "PENDING"),
        })

    total_wagered = sum(b.wager for b in future_bets)
    total_payout = sum(b.payout for b in future_bets if b.payout is not None)

    return render(request, "core/user_profile.html", {
        "profile_user": target_user,
        "profile": profile,
        "recent_date_groups": recent_date_groups,
        "parlays": parlays[:10],
        "future_bets": future_bets[:10],
        "total_picks_all": total_picks_all,
        "wins_all": wins_all,
        "losses_all": losses_all,
        "pending_all": pending_all,
        "total_wagered": total_wagered,
        "total_payout": total_payout,
        "is_own_profile": target_user == request.user,
        "ticker_stocks": get_top_stocks_by_sector(),
    })


@login_required
def notifications_json(request):
    from django.http import JsonResponse
    from django.utils.timesince import timesince
    notifs = Notification.objects.filter(user=request.user).order_by("-created_at")[:10]
    unread = Notification.objects.filter(user=request.user, is_read=False).count()
    data = [
        {
            "id": n.id,
            "message": n.message,
            "type": n.notification_type,
            "is_read": n.is_read,
            "time_ago": timesince(n.created_at) + " ago",
        }
        for n in notifs
    ]
    return JsonResponse({"notifications": data, "unread": unread})


@login_required
def mark_notifications_read(request):
    from django.http import JsonResponse
    if request.method == "POST":
        Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    return JsonResponse({"ok": True})


def stock_news(request, ticker):
    from django.http import JsonResponse
    ticker = ticker.upper().strip()
    try:
        stock = yf.Ticker(ticker)

        # News
        raw = stock.news[:5] if stock.news else []
        articles = []
        for item in raw:
            content = item.get('content', {})
            articles.append({
                'title': content.get('title') or item.get('title', ''),
                'publisher': (content.get('provider', {}) or {}).get('displayName') or item.get('publisher', ''),
                'link': (content.get('canonicalUrl', {}) or {}).get('url') or item.get('link', ''),
                'published': item.get('providerPublishTime', ''),
            })

        # P/E ratio — trailingPE direct, then manual price/EPS fallback
        pe = None
        try:
            info = stock.info
            pe = info.get('trailingPE')
            if pe is None:
                eps = info.get('trailingEps')
                price = info.get('currentPrice') or info.get('regularMarketPrice')
                if eps and price and float(eps) != 0:
                    pe = round(float(price) / float(eps), 2)
            if pe is not None:
                pe = round(float(pe), 2)
        except Exception:
            pe = None

        return JsonResponse({'ticker': ticker, 'news': articles, 'pe_ratio': pe})
    except Exception as e:
        return JsonResponse({'ticker': ticker, 'news': [], 'pe_ratio': None, 'error': str(e)})
