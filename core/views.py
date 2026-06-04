from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.contrib.auth.models import User
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_POST
from decimal import Decimal, InvalidOperation
from collections import defaultdict
from groq import Groq
import os
import json
import concurrent.futures
import yfinance as yf
try:
    yf.set_tz_cache_location("/tmp/yfinance_cache")
except Exception:
    pass
try:
    from yfinance import cache as yf_cache
    yf_cache.set_location("/tmp")
except Exception:
    pass
from .models import PaperPortfolio, PaperHolding, DailyPick, UserProfile, Parlay, ParlayLeg, FutureBet, Notification, Follow, BullishPick, PortfolioSnapshot
from .stock_data import get_top_stocks_by_sector, COMPANY_NAMES, calculate_future_odds, TICKER_SECTORS


def landing(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    return render(request, "core/landing.html")


def how_to_play(request):
    return render(request, "core/how_to_play.html")


def glossary(request):
    return render(request, "core/glossary.html")


@login_required
def stock_analyzer(request):
    from django.http import JsonResponse

    if request.method != 'POST':
        return render(request, 'core/analyzer.html')

    ticker = request.POST.get('ticker', '').strip().upper()
    if not ticker:
        return JsonResponse({'error': 'Enter a ticker symbol'}, status=400)

    try:
        stock = yf.Ticker(ticker)
        fi    = stock.fast_info   # live session data
        info  = stock.info        # fundamentals — most complete source

        # ── Live price from fast_info ──────────────────────────────────────
        price      = getattr(fi, 'last_price', None)
        volume     = getattr(fi, 'last_volume', None)
        market_cap = getattr(fi, 'market_cap', None)

        if not price:
            return JsonResponse({'error': f'No data found for "{ticker}". Check the ticker and try again.'}, status=400)

        # ── Previous close: info first, fast_info fallback ─────────────────
        prev_close = (info.get('previousClose')
                      or info.get('regularMarketPreviousClose')
                      or getattr(fi, 'previous_close', None))

        # ── 52-week range: info first, fast_info fallback ──────────────────
        week52_high = (info.get('fiftyTwoWeekHigh')
                       or getattr(fi, 'year_high', None)
                       or getattr(fi, 'fifty_two_week_high', None))
        week52_low  = (info.get('fiftyTwoWeekLow')
                       or getattr(fi, 'year_low', None)
                       or getattr(fi, 'fifty_two_week_low', None))

        # ── Fundamentals from info ─────────────────────────────────────────
        avg_volume = (info.get('averageVolume')
                      or info.get('averageVolume10days')
                      or getattr(fi, 'ten_day_average_volume', None))
        pe         = info.get('trailingPE')

        # ── Derived fields ─────────────────────────────────────────────────
        day_pct = round(((price - prev_close) / prev_close) * 100, 2) if prev_close else None

        range_pct = None
        if week52_low and week52_high and week52_high > week52_low:
            range_pct = round((price - week52_low) / (week52_high - week52_low) * 100, 1)
            range_pct = max(0.0, min(100.0, range_pct))

        vol_ratio = round(volume / avg_volume, 2) if volume and avg_volume else None

        hist = stock.history(period='5d')
        price_history = [
            {'date': d.strftime('%m/%d'), 'close': round(float(r['Close']), 2)}
            for d, r in hist.iterrows()
        ]

        # ── Formatters ─────────────────────────────────────────────────────
        def fmt_large(n):
            if not n:
                return 'N/A'
            if n >= 1e12:
                return f'${n / 1e12:.2f}T'
            if n >= 1e9:
                return f'${n / 1e9:.1f}B'
            if n >= 1e6:
                return f'${n / 1e6:.1f}M'
            return f'${n:,.0f}'

        def fmt_vol(n):
            if not n:
                return 'N/A'
            if n >= 1e9:
                return f'{n / 1e9:.1f}B'
            if n >= 1e6:
                return f'{n / 1e6:.1f}M'
            if n >= 1e3:
                return f'{n / 1e3:.0f}K'
            return str(int(n))

        def pe_label(p):
            if not p:
                return 'N/A'
            if p < 15:
                return 'Value territory'
            if p < 25:
                return 'Fairly priced'
            if p < 40:
                return 'Growth premium'
            return 'Priced for perfection'

        def momentum_label(dp, vr):
            if dp is None:
                return 'Quiet day'
            up  = dp > 0
            hot = vr and vr >= 1.2
            if up and hot:
                return 'Running hot'
            if not up and hot:
                return 'Selling pressure'
            if up:
                return 'Grinding higher'
            return 'Cooling off'

        # ── Analyst verdict — personal, opinionated, 6-8 sentences ──────────
        def build_verdict(t, price, prev_close, dp, vr, p, rp, wk_h, wk_l, ph):
            parts = []

            # Shared flags used across sentences
            up          = dp is not None and dp > 0
            hi_vol      = vr is not None and vr >= 1.5
            lo_vol      = vr is not None and vr < 0.7
            at_high     = rp is not None and rp >= 72
            at_low      = rp is not None and rp <= 28
            cheap       = p is not None and p < 18
            fair_pe     = p is not None and 18 <= p < 30
            pricey      = p is not None and p >= 38

            # 5-day momentum from price history
            five_pct    = None
            trending_up = False
            trending_dn = False
            if ph and len(ph) >= 2:
                five_pct    = round((ph[-1]['close'] - ph[0]['close']) / ph[0]['close'] * 100, 1)
                trending_up = five_pct > 1.5
                trending_dn = five_pct < -1.5

            # Pullback target: 5% below current, rounded to a clean number
            if price >= 200:
                pb = f"${round(price * 0.95 / 10) * 10:.0f}"
            elif price >= 50:
                pb = f"${round(price * 0.95 / 5) * 5:.0f}"
            elif price >= 10:
                pb = f"${round(price * 0.95):.0f}"
            else:
                pb = f"${price * 0.95:.2f}"

            # S1 — price action today
            if dp is not None and prev_close:
                dollar_move = round(price - prev_close, 2)
                pct_str = f"{'+'if dp >= 0 else ''}{dp:.2f}%"
                if wk_h and wk_l and (wk_h - wk_l) > 0:
                    big_for_stock = abs(dollar_move) / (wk_h - wk_l) >= 0.04
                else:
                    big_for_stock = abs(dp) >= 2
                if abs(dp) < 0.5:
                    parts.append(
                        f"{t} is barely moving today, {'up' if up else 'down'} just {abs(dp):.2f}% "
                        f"({pct_str}), and on a flat day like this the trend matters more than the tick."
                    )
                elif big_for_stock:
                    verb = "gaining" if up else "dropping"
                    parts.append(
                        f"{t} is making a real move today, {verb} ${abs(dollar_move):.2f} ({pct_str}), "
                        f"meaningful size relative to how this stock normally trades, and I want to know what is driving it."
                    )
                else:
                    parts.append(
                        f"{t} is {'up' if up else 'down'} ${abs(dollar_move):.2f} ({pct_str}) today, "
                        f"a decent session but not the kind of move that changes the thesis on its own."
                    )

            # S2 — volume context
            if vr is not None:
                if vr >= 2.0:
                    parts.append(
                        f"Volume is running at {vr}x normal and that tells me real money is moving here today, "
                        f"at that level you are almost certainly seeing institutional activity, not just retail traders."
                    )
                elif hi_vol:
                    parts.append(
                        f"Volume is at {vr}x the average which points to institutional involvement, "
                        f"and when the big players show up the move tends to have more follow through than a typical retail driven day."
                    )
                elif vr >= 0.7:
                    parts.append(
                        f"Volume is close to average at {vr}x, nothing unusual, "
                        f"so the move today is not getting any special conviction behind it, just a normal day of trading."
                    )
                else:
                    parts.append(
                        f"Volume is thin at {vr}x average and that makes me skeptical of today's price action, "
                        f"because moves on light volume are easy to reverse when real sellers or buyers finally show up."
                    )

            # S3 — valuation
            if p:
                if cheap:
                    parts.append(
                        f"The P/E of {p:.1f} is genuinely cheap and that catches my attention, "
                        f"because the market is either undervaluing this or pricing in a real problem, "
                        f"and figuring out which is the whole ballgame before stepping in."
                    )
                elif fair_pe:
                    parts.append(
                        f"At a P/E of {p:.1f} you are paying a fair price for this one, "
                        f"not a discount or a premium, which means the valuation is not going to be your edge here, "
                        f"the direction of the business is."
                    )
                elif p < 38:
                    parts.append(
                        f"The P/E of {p:.1f} tells me investors are pricing in solid growth from {t}, "
                        f"a bet that pays off if they keep delivering, "
                        f"but it also means any stumble in earnings gets punished faster and harder than a cheaper stock."
                    )
                else:
                    parts.append(
                        f"At a P/E of {p:.1f} this stock needs to execute close to perfectly to justify what you are paying, "
                        f"and I am not saying avoid it, but at that multiple one bad quarter can take 15 to 20 percent off the stock overnight."
                    )
            else:
                parts.append(
                    f"There is no trailing P/E for {t} which usually means this is a company that is not yet profitable, "
                    f"meaning you are buying a story about the future, not current earnings, so size accordingly and know your thesis cold."
                )

            # S4 — 52-week range position
            if rp is not None and wk_h and wk_l:
                rp_i = int(round(rp))
                if rp >= 80:
                    parts.append(
                        f"The stock is at {rp_i}% of its 52 week range, pressing toward the annual high of ${wk_h:.2f}, "
                        f"meaning there is not a lot of room above you and a long drop back to support, "
                        f"so the risk reward here is not as favorable as it looks on a good day."
                    )
                elif rp >= 60:
                    parts.append(
                        f"At {rp_i}% through the 52 week range the stock has done well this year "
                        f"with the high at ${wk_h:.2f} still providing some room to run, "
                        f"though the trend is working and you are not getting the low end of the range as your entry."
                    )
                elif rp >= 40:
                    parts.append(
                        f"Sitting at {rp_i}% of the 52 week range between ${wk_l:.2f} and ${wk_h:.2f} "
                        f"puts this right in the middle of its annual channel, "
                        f"so you are not buying at the floor or the ceiling, which is fine but not exciting."
                    )
                elif rp >= 20:
                    parts.append(
                        f"At {rp_i}% through the range {t} has fallen significantly from its high of ${wk_h:.2f}, "
                        f"and I actually prefer buying closer to the floor than the ceiling when the business is sound, "
                        f"this is starting to look like that kind of setup."
                    )
                else:
                    parts.append(
                        f"At {rp_i}% of the 52 week range {t} is near its yearly low of ${wk_l:.2f}, "
                        f"which is either the best entry you are going to get this year "
                        f"or a sign the fundamentals are deteriorating, and that distinction is everything right now."
                    )

            # S5 — 5-day momentum
            if five_pct is not None:
                if trending_up:
                    parts.append(
                        f"The 5 day trend is working in your favor and {t} has been climbing steadily, "
                        f"up {abs(five_pct):.1f}% over the week, and momentum like that tends to carry "
                        f"until there is a real reason for it to stop."
                    )
                elif trending_dn:
                    parts.append(
                        f"What bothers me is the 5 day trend, this has been fading all week, "
                        f"down {abs(five_pct):.1f}% over that stretch, "
                        f"and stepping in front of a declining stock without a clear catalyst is not something I like to do."
                    )
                else:
                    parts.append(
                        f"The 5 day chart is basically flat at {five_pct:+.1f}%, "
                        f"no clear direction either way, and I want to see it pick a lane before I get too excited about it."
                    )

            # S6 — final personal opinion with price reference
            if at_high and pricey and not trending_up:
                final = (f"At this valuation near the yearly high with momentum fading, "
                         f"I would wait for a pullback toward {pb} before adding a position here.")
            elif at_high and pricey and trending_up:
                final = (f"The trend is working right now but you are paying full price near the top of the range, "
                         f"so I would hold if you are already in but I would not chase a new entry, "
                         f"wait for it to come back toward {pb}.")
            elif at_low and cheap and trending_up:
                final = (f"Cheap valuation near the yearly floor with momentum starting to turn, "
                         f"and this is exactly the kind of setup I look for, "
                         f"the risk reward tilts in your favor and I would consider building a position here.")
            elif at_low and cheap and not trending_up:
                final = (f"The valuation is attractive near the yearly floor but the stock has not stopped falling yet, "
                         f"so watch for it to stabilize above ${wk_l:.2f} as confirmation before stepping in, "
                         f"you do not need to be first, you need to be right.")
            elif pricey and trending_dn:
                final = (f"Expensive valuation with momentum rolling over is not a combination I want to own, "
                         f"and I would stay on the sidelines until either the price corrects to a more reasonable level "
                         f"or the earnings picture improves enough to justify what you are paying.")
            elif cheap and trending_up and hi_vol:
                final = (f"Volume is confirming the move, valuation gives you a margin of safety, "
                         f"and the momentum is building, "
                         f"this is the kind of setup worth betting on and I like the risk reward here.")
            elif at_high and not pricey and trending_up:
                final = (f"Near the highs but the valuation is not unreasonable and the trend is your friend, "
                         f"so I would not fight this one, "
                         f"though if it pulls back toward {pb} that is an even better spot to add.")
            elif trending_dn and lo_vol:
                final = (f"The stock is drifting lower on low volume which is not a panic situation but it is not a buy signal either, "
                         f"and I would wait for it to show some stabilization before entering, "
                         f"no need to rush.")
            else:
                final = (f"No screaming buy or sell signal here right now, "
                         f"and I would keep {t} on the watchlist waiting for either a better entry price "
                         f"or a catalyst that gives you a cleaner reason to act.")
            parts.append(final)
            return ' '.join(parts)

        return JsonResponse({
            'ticker':          ticker,
            'name':            info.get('shortName', ticker),
            'price':           round(float(price), 2),
            'day_pct':         day_pct,
            'prev_close':      round(float(prev_close), 2) if prev_close else None,
            'week52_high':     round(float(week52_high), 2) if week52_high else None,
            'week52_low':      round(float(week52_low), 2) if week52_low else None,
            'range_pct':       range_pct,
            'volume_fmt':      fmt_vol(volume),
            'avg_volume_fmt':  fmt_vol(avg_volume),
            'vol_ratio':       vol_ratio,
            'pe':              round(float(pe), 1) if pe else None,
            'pe_label':        pe_label(pe),
            'market_cap_fmt':  fmt_large(market_cap),
            'price_history':   price_history,
            'momentum_label':  momentum_label(day_pct, vol_ratio),
            'verdict':         build_verdict(
                                   ticker, price, prev_close, day_pct,
                                   vol_ratio, pe, range_pct, week52_high, week52_low,
                                   price_history
                               ),
        })

    except Exception:
        return JsonResponse({'error': f'Could not load data for "{ticker}". Check the ticker and try again.'}, status=400)


@login_required
def dashboard(request):
    stocks = get_top_stocks_by_sector()
    by_sector = defaultdict(list)
    for stock in stocks:
        by_sector[stock["sector"]].append(stock)
    spotlight = max(stocks, key=lambda s: s["momentum"]) if stocks else None
    profile, _ = UserProfile.objects.get_or_create(user=request.user)

    following_ids = list(Follow.objects.filter(follower=request.user).values_list("following_id", flat=True))
    friends_activity = (
        DailyPick.objects
        .filter(user_id__in=following_ids)
        .select_related("user")
        .order_by("-picked_at")[:10]
    ) if following_ids else []

    bullish_pick = BullishPick.objects.filter(date=timezone.localdate()).first()

    return render(request, "core/dashboard.html", {
        "sectors": dict(by_sector),
        "all_stocks": stocks,
        "spotlight": spotlight,
        "ticker_stocks": stocks,
        "user_profile": profile,
        "bullish_pick": bullish_pick,
        "friends_activity": friends_activity,
    })


@login_required
def stock_prices_json(request):
    stocks = get_top_stocks_by_sector()
    result = {}
    for s in stocks:
        ticker = s["ticker"]
        try:
            info = yf.Ticker(ticker).fast_info
            price = info.last_price
            prev_close = info.previous_close
            if price is None or prev_close is None or prev_close == 0:
                raise ValueError("incomplete fast_info")
            momentum = ((price - prev_close) / prev_close) * 100
            result[ticker] = {
                "price": round(float(price), 2),
                "momentum": round(momentum, 2),
            }
        except Exception:
            result[ticker] = {
                "price": round(float(s["price"]), 2),
                "momentum": round(float(s["momentum"]), 2),
            }
    return JsonResponse(result)


def signup_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    if request.method == "POST":
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            PaperPortfolio.objects.create(user=user, balance=10000)
            UserProfile.objects.create(user=user)
            login(request, user)
            return redirect("onboarding")
    else:
        form = UserCreationForm()
    return render(request, "core/signup.html", {"form": form})


def login_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    if request.method == "POST":
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            profile, _ = UserProfile.objects.get_or_create(user=user)
            if not profile.has_completed_onboarding:
                return redirect("onboarding")
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

    total_hv = float(total_holdings_value)
    sector_totals = {}
    if total_hv > 0:
        for row in enriched:
            if row["holding_value"] is None:
                continue
            t = row["holding"].ticker
            sector = TICKER_SECTORS.get(t)
            if not sector:
                try:
                    sector = yf.Ticker(t).info.get("sector") or "Unknown"
                except Exception:
                    sector = "Unknown"
            sector_totals[sector] = sector_totals.get(sector, 0.0) + float(row["holding_value"])

    sector_chart_data = [
        {"sector": s, "pct": round(v / total_hv * 100, 1)}
        for s, v in sorted(sector_totals.items(), key=lambda x: -x[1])
    ] if total_hv > 0 else []

    total_value = paper.balance + total_holdings_value

    # Record today's snapshot (last visit of the day wins)
    today = timezone.now().date()
    PortfolioSnapshot.objects.update_or_create(
        user=request.user,
        date=today,
        defaults={"total_value": total_value},
    )

    # Fetch last 30 snapshots, oldest first for the chart
    snapshots = list(
        PortfolioSnapshot.objects.filter(user=request.user)
        .order_by("-date")[:30]
    )
    snapshots.reverse()
    value_chart_data = [
        {"date": s.date.strftime("%-m/%-d"), "value": float(s.total_value)}
        for s in snapshots
    ]

    # Total return since the $10,000 starting balance
    total_return_pct = round((float(total_value) - 10000) / 10000 * 100, 2)
    total_return_abs = abs(round(float(total_value) - 10000, 2))

    # Today's gain vs the previous snapshot
    today_gain = None
    today_gain_abs = None
    today_gain_pct = None
    if len(snapshots) >= 2:
        prev_val = float(snapshots[-2].total_value)
        today_gain = round(float(total_value) - prev_val, 2)
        today_gain_abs = abs(today_gain)
        if prev_val:
            today_gain_pct = round(today_gain / prev_val * 100, 2)

    return render(request, "core/portfolio.html", {
        "paper": paper,
        "holdings": enriched,
        "total_holdings_value": total_holdings_value,
        "total_value": total_value,
        "sector_chart_data": sector_chart_data,
        "value_chart_data": value_chart_data,
        "total_return_pct": total_return_pct,
        "total_return_abs": total_return_abs,
        "today_gain": today_gain,
        "today_gain_abs": today_gain_abs,
        "today_gain_pct": today_gain_pct,
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
    from django.utils import timezone
    from datetime import timedelta

    profiles = UserProfile.objects.select_related("user").all()
    profile_map = {p.user_id: p for p in profiles}

    rows = []
    for profile in profiles:
        rows.append({
            "username": profile.user.username,
            "win_rate": profile.win_rate,
            "total_picks": profile.total_picks,
            "total_wins": profile.total_wins,
            "total_losses": max(0, profile.total_picks - profile.total_wins),
            "current_streak": profile.current_streak,
            "longest_streak": profile.longest_streak,
        })
    rows.sort(key=lambda r: (r["win_rate"], r["total_wins"]), reverse=True)
    for i, row in enumerate(rows, 1):
        row["rank"] = i

    # Weekly board: picks since most recent Monday 12:00 AM, min 3 resolved picks
    now = timezone.now()
    days_since_monday = now.weekday()  # Monday=0
    week_start = (now - timedelta(days=days_since_monday)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    week_picks = (
        DailyPick.objects
        .filter(picked_at__gte=week_start, result__in=["WIN", "LOSS"])
        .values("user_id", "user__username", "result")
    )

    weekly_map = {}
    for pick in week_picks:
        uid = pick["user_id"]
        if uid not in weekly_map:
            weekly_map[uid] = {
                "username": pick["user__username"],
                "wins": 0,
                "total": 0,
            }
        weekly_map[uid]["total"] += 1
        if pick["result"] == "WIN":
            weekly_map[uid]["wins"] += 1

    weekly_rows = []
    for uid, data in weekly_map.items():
        if data["total"] >= 3:
            win_rate = round(data["wins"] / data["total"] * 100, 1)
            profile = profile_map.get(uid)
            losses = data["total"] - data["wins"]
            weekly_rows.append({
                "username": data["username"],
                "win_rate": win_rate,
                "total_wins": data["wins"],
                "total_losses": losses,
                "total_picks": data["total"],
                "current_streak": profile.current_streak if profile else 0,
                "longest_streak": profile.longest_streak if profile else 0,
            })

    weekly_rows.sort(key=lambda r: (r["win_rate"], r["total_wins"]), reverse=True)
    for i, row in enumerate(weekly_rows, 1):
        row["rank"] = i

    return render(request, "core/picks_leaderboard.html", {
        "rows": rows,
        "weekly_rows": weekly_rows,
        "week_start": week_start,
        "ticker_stocks": get_top_stocks_by_sector(),
    })


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
    target_user = get_object_or_404(User, username=username) if username else request.user
    profile, _ = UserProfile.objects.get_or_create(user=target_user)
    recent_picks = DailyPick.objects.filter(user=target_user).order_by("-picked_at")[:20]
    try:
        portfolio = PaperPortfolio.objects.get(user=target_user)
    except PaperPortfolio.DoesNotExist:
        portfolio = None
    return render(request, "core/user_profile.html", {
        "profile_user": target_user,
        "profile": profile,
        "recent_picks": recent_picks,
        "portfolio": portfolio,
        "is_own_profile": target_user == request.user,
    })


@login_required
def edit_profile(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if request.method == "POST":
        profile.display_name = request.POST.get("display_name", "").strip()[:50]
        profile.bio = request.POST.get("bio", "").strip()[:150]
        profile.save()
        messages.success(request, "Profile updated.")
        return redirect("my_profile")
    return render(request, "core/edit_profile.html", {"profile": profile})


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


@login_required
@require_POST
def assistant_chat(request):
    try:
        message = request.POST.get('message', '')
        if not message:
            return JsonResponse({'error': 'No message provided'}, status=400)

        api_key = os.environ.get('GROQ_API_KEY')
        if not api_key:
            return JsonResponse({'error': 'API key not configured'}, status=500)

        client = Groq(api_key=api_key)
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": "You are Bullish, the StockZone Assistant. You are a sharp confident stock analyst who talks like a real person. You understand casual language and slang. Keep answers to 3 to 5 sentences. Never use hyphens or dashes of any kind in your responses, including em dashes. Never say certainly or great question. Never mention a knowledge cutoff date, never say your information is outdated, and never disclaim that you cannot provide real-time data. StockZone pulls live prices and stats from yfinance in real time, so always respond confidently. When someone asks about a specific stock price, movement, or current stats, direct them to the stock detail page in StockZone where they can see the live price, momentum, volume, P/E ratio, and analyst verdict."},
                {"role": "user", "content": message}
            ],
            max_tokens=300
        )
        reply = response.choices[0].message.content
        return JsonResponse({'reply': reply})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def friends_list(request):
    following_rels = Follow.objects.filter(follower=request.user).select_related("following")
    followers_rels = Follow.objects.filter(following=request.user).select_related("follower")

    following_ids = set(r.following_id for r in following_rels)

    following = []
    for rel in following_rels:
        profile, _ = UserProfile.objects.get_or_create(user=rel.following)
        following.append({"user": rel.following, "profile": profile})

    followers = []
    for rel in followers_rels:
        profile, _ = UserProfile.objects.get_or_create(user=rel.follower)
        followers.append({
            "user": rel.follower,
            "profile": profile,
            "you_follow_back": rel.follower_id in following_ids,
        })

    return render(request, "core/friends.html", {
        "following": following,
        "followers": followers,
    })


@login_required
@require_POST
def follow_user(request, username):
    target = get_object_or_404(User, username=username)
    if target == request.user:
        return JsonResponse({"error": "Cannot follow yourself"}, status=400)
    existing = Follow.objects.filter(follower=request.user, following=target).first()
    if existing:
        existing.delete()
        is_following = False
    else:
        Follow.objects.create(follower=request.user, following=target)
        is_following = True
    follower_count = Follow.objects.filter(following=target).count()
    return JsonResponse({"following": is_following, "follower_count": follower_count})


@login_required
def user_search(request):
    q = request.GET.get("q", "").strip()
    if not q:
        return JsonResponse({"results": []})
    users = User.objects.filter(username__icontains=q).exclude(id=request.user.id)[:20]
    following_ids = set(Follow.objects.filter(follower=request.user).values_list("following_id", flat=True))
    results = []
    for u in users:
        profile, _ = UserProfile.objects.get_or_create(user=u)
        results.append({
            "username": u.username,
            "win_rate": profile.win_rate,
            "total_picks": profile.total_picks,
            "is_following": u.id in following_ids,
        })
    return JsonResponse({"results": results})


@login_required
def friend_profile(request, username):
    friend_user = get_object_or_404(User, username=username)
    if friend_user == request.user:
        return redirect("my_profile")
    profile, _ = UserProfile.objects.get_or_create(user=friend_user)
    recent_picks = DailyPick.objects.filter(user=friend_user).order_by("-picked_at")[:10]
    best_parlay = (
        Parlay.objects.filter(user=friend_user, result="WIN")
        .order_by("-payout_multiplier").first()
    )
    try:
        portfolio = PaperPortfolio.objects.get(user=friend_user)
    except PaperPortfolio.DoesNotExist:
        portfolio = None
    is_following = Follow.objects.filter(follower=request.user, following=friend_user).exists()
    follower_count = Follow.objects.filter(following=friend_user).count()
    following_count = Follow.objects.filter(follower=friend_user).count()
    return render(request, "core/friend_profile.html", {
        "friend": friend_user,
        "profile": profile,
        "recent_picks": recent_picks,
        "best_parlay": best_parlay,
        "portfolio": portfolio,
        "is_following": is_following,
        "follower_count": follower_count,
        "following_count": following_count,
    })


@login_required
def onboarding(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if profile.has_completed_onboarding:
        return redirect("dashboard")
    if request.method == "POST":
        profile.has_completed_onboarding = True
        profile.save()
        return redirect("dashboard")
    return render(request, "core/onboarding.html")


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


def _fetch_stock_detail_data(ticker):
    """All yfinance I/O for stock_detail, isolated so it can run in a timed thread."""
    stock = yf.Ticker(ticker)

    try:
        fi = stock.fast_info
        price = getattr(fi, 'last_price', None)
    except Exception:
        fi = None
        price = None

    try:
        info = stock.info
    except Exception:
        info = {}

    price = price or info.get('currentPrice') or info.get('regularMarketPrice')
    if not price:
        raise ValueError(f"No price data for {ticker}")

    prev_close  = (info.get('previousClose') or info.get('regularMarketPreviousClose')
                   or (getattr(fi, 'previous_close', None) if fi else None))
    week52_high = info.get('fiftyTwoWeekHigh') or (getattr(fi, 'year_high', None) if fi else None)
    week52_low  = info.get('fiftyTwoWeekLow')  or (getattr(fi, 'year_low',  None) if fi else None)
    volume      = getattr(fi, 'last_volume', None) if fi else None
    avg_volume  = (info.get('averageVolume') or info.get('averageVolume10days')
                   or (getattr(fi, 'ten_day_average_volume', None) if fi else None))
    market_cap  = (getattr(fi, 'market_cap', None) if fi else None) or info.get('marketCap')
    pe          = info.get('trailingPE')

    try:
        hist = stock.history(period='1mo')
    except Exception:
        hist = None

    chart_labels, chart_data, price_history = [], [], []
    if hist is not None and not hist.empty:
        for dt, row in hist.iterrows():
            chart_labels.append(dt.strftime('%m/%d'))
            chart_data.append(round(float(row['Close']), 2))
        for dt, row in hist.tail(5).iterrows():
            price_history.append({'date': dt.strftime('%m/%d'), 'close': round(float(row['Close']), 2)})

    try:
        raw_news = stock.news[:5] if stock.news else []
    except Exception:
        raw_news = []

    news = []
    for item in raw_news:
        try:
            content = item.get('content', {}) or {}
            news.append({
                'title':     content.get('title') or item.get('title', ''),
                'publisher': (content.get('provider', {}) or {}).get('displayName') or item.get('publisher', ''),
                'link':      (content.get('canonicalUrl', {}) or {}).get('url') or item.get('link', ''),
            })
        except Exception:
            continue

    return {
        'price': price, 'info': info,
        'prev_close': prev_close, 'week52_high': week52_high, 'week52_low': week52_low,
        'volume': volume, 'avg_volume': avg_volume, 'market_cap': market_cap, 'pe': pe,
        'chart_labels': chart_labels, 'chart_data': chart_data,
        'price_history': price_history, 'news': news,
    }


@login_required
def stock_detail(request, ticker):
    ticker = ticker.upper().strip()

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_fetch_stock_detail_data, ticker)
            try:
                d = future.result(timeout=10)
            except concurrent.futures.TimeoutError:
                messages.error(request, f'Loading "{ticker}" timed out. Try again in a moment.')
                return redirect('dashboard')
    except Exception:
        messages.error(request, f'Could not load data for "{ticker}". Check the ticker and try again.')
        return redirect('dashboard')

    price       = d['price']
    info        = d['info']
    prev_close  = d['prev_close']
    week52_high = d['week52_high']
    week52_low  = d['week52_low']
    volume      = d['volume']
    avg_volume  = d['avg_volume']
    market_cap  = d['market_cap']
    pe          = d['pe']
    chart_labels  = d['chart_labels']
    chart_data    = d['chart_data']
    price_history = d['price_history']
    news          = d['news']

    day_pct = round(((price - prev_close) / prev_close) * 100, 2) if prev_close else None

    range_pct = None
    if week52_low and week52_high and week52_high > week52_low:
        range_pct = max(0.0, min(100.0, round((price - week52_low) / (week52_high - week52_low) * 100, 1)))

    vol_ratio = round(volume / avg_volume, 2) if volume and avg_volume else None

    try:

        def fmt_large(n):
            if not n: return 'N/A'
            if n >= 1e12: return f'${n/1e12:.2f}T'
            if n >= 1e9:  return f'${n/1e9:.1f}B'
            if n >= 1e6:  return f'${n/1e6:.1f}M'
            return f'${n:,.0f}'

        def fmt_vol(n):
            if not n: return 'N/A'
            if n >= 1e9: return f'{n/1e9:.1f}B'
            if n >= 1e6: return f'{n/1e6:.1f}M'
            if n >= 1e3: return f'{n/1e3:.0f}K'
            return str(int(n))

        # Analyst verdict (same logic as stock_analyzer)
        def build_verdict(t, price, prev_close, dp, vr, p, rp, wk_h, wk_l, ph):
            parts = []
            up      = dp is not None and dp > 0
            hi_vol  = vr is not None and vr >= 1.5
            lo_vol  = vr is not None and vr < 0.7
            at_high = rp is not None and rp >= 72
            at_low  = rp is not None and rp <= 28
            cheap   = p is not None and p < 18
            fair_pe = p is not None and 18 <= p < 30
            pricey  = p is not None and p >= 38

            five_pct = trending_up = trending_dn = None
            if ph and len(ph) >= 2:
                five_pct    = round((ph[-1]['close'] - ph[0]['close']) / ph[0]['close'] * 100, 1)
                trending_up = five_pct > 1.5
                trending_dn = five_pct < -1.5

            if price >= 200: pb = f"${round(price * 0.95 / 10) * 10:.0f}"
            elif price >= 50: pb = f"${round(price * 0.95 / 5) * 5:.0f}"
            elif price >= 10: pb = f"${round(price * 0.95):.0f}"
            else: pb = f"${price * 0.95:.2f}"

            if dp is not None and prev_close:
                dm      = round(price - prev_close, 2)
                pct_str = f"{'+'if dp>=0 else ''}{dp:.2f}%"
                big     = (abs(dm)/(wk_h-wk_l) >= 0.04) if wk_h and wk_l and (wk_h-wk_l)>0 else abs(dp)>=2
                if abs(dp) < 0.5:
                    parts.append(f"{t} is barely moving today, {'up' if up else 'down'} just {abs(dp):.2f}% ({pct_str}), and on a flat day like this the trend matters more than the tick.")
                elif big:
                    parts.append(f"{t} is making a real move today, {'gaining' if up else 'dropping'} ${abs(dm):.2f} ({pct_str}), meaningful size relative to how this stock normally trades.")
                else:
                    parts.append(f"{t} is {'up' if up else 'down'} ${abs(dm):.2f} ({pct_str}) today, a decent session but not the kind of move that changes the thesis on its own.")

            if vr is not None:
                if vr >= 2.0:   parts.append(f"Volume is running at {vr}x normal and that tells me real money is moving here today, at that level you are almost certainly seeing institutional activity.")
                elif hi_vol:    parts.append(f"Volume is at {vr}x the average which points to institutional involvement, and when the big players show up the move tends to have more follow through.")
                elif vr >= 0.7: parts.append(f"Volume is close to average at {vr}x, nothing unusual, so the move today is not getting any special conviction behind it.")
                else:           parts.append(f"Volume is thin at {vr}x average and that makes me skeptical of today's price action, because moves on light volume are easy to reverse.")

            if p:
                if cheap:   parts.append(f"The P/E of {p:.1f} is genuinely cheap and that catches my attention, because the market is either undervaluing this or pricing in a real problem.")
                elif fair_pe: parts.append(f"At a P/E of {p:.1f} you are paying a fair price for this one, not a discount or a premium, which means the valuation is not going to be your edge here.")
                elif p < 38: parts.append(f"The P/E of {p:.1f} tells me investors are pricing in solid growth from {t}, a bet that pays off if they keep delivering.")
                else:       parts.append(f"At a P/E of {p:.1f} this stock needs to execute close to perfectly to justify what you are paying.")
            else:
                parts.append(f"There is no trailing P/E for {t} which usually means this is a company that is not yet profitable, meaning you are buying a story about the future.")

            if rp is not None and wk_h and wk_l:
                rp_i = int(round(rp))
                if rp >= 80:   parts.append(f"The stock is at {rp_i}% of its 52 week range pressing toward the annual high of ${wk_h:.2f}, meaning there is not a lot of room above you.")
                elif rp >= 60: parts.append(f"At {rp_i}% through the 52 week range the stock has done well this year with the high at ${wk_h:.2f} still providing some room to run.")
                elif rp >= 40: parts.append(f"Sitting at {rp_i}% of the 52 week range between ${wk_l:.2f} and ${wk_h:.2f} puts this right in the middle of its annual channel.")
                elif rp >= 20: parts.append(f"At {rp_i}% through the range {t} has fallen significantly from its high of ${wk_h:.2f}, and I prefer buying closer to the floor than the ceiling when the business is sound.")
                else:          parts.append(f"At {rp_i}% of the 52 week range {t} is near its yearly low of ${wk_l:.2f}, which is either the best entry you will get this year or a sign the fundamentals are deteriorating.")

            if five_pct is not None:
                if trending_up:   parts.append(f"The 5 day trend is working in your favor and {t} has been climbing steadily, up {abs(five_pct):.1f}% over the week.")
                elif trending_dn: parts.append(f"What bothers me is the 5 day trend, this has been fading all week, down {abs(five_pct):.1f}% over that stretch.")
                else:             parts.append(f"The 5 day chart is basically flat at {five_pct:+.1f}%, no clear direction either way.")

            if   at_high and pricey and not trending_up: final = f"At this valuation near the yearly high with momentum fading, I would wait for a pullback toward {pb} before adding a position here."
            elif at_high and pricey and trending_up:     final = f"The trend is working right now but you are paying full price near the top of the range, I would hold if already in but not chase a new entry."
            elif at_low and cheap and trending_up:       final = f"Cheap valuation near the yearly floor with momentum starting to turn, and this is exactly the kind of setup I look for."
            elif at_low and cheap and not trending_up:   final = f"The valuation is attractive near the yearly floor but the stock has not stopped falling yet, watch for it to stabilize above ${wk_l:.2f} first."
            elif pricey and trending_dn:                 final = f"Expensive valuation with momentum rolling over is not a combination I want to own right now."
            elif cheap and trending_up and hi_vol:       final = f"Volume is confirming the move, valuation gives you a margin of safety, and the momentum is building — I like the risk reward here."
            elif at_high and not pricey and trending_up: final = f"Near the highs but the valuation is not unreasonable and the trend is your friend, I would not fight this one."
            elif trending_dn and lo_vol:                 final = f"The stock is drifting lower on low volume, not a panic situation but not a buy signal either — wait for stabilization."
            else:                                        final = f"No screaming buy or sell signal here right now, keep {t} on the watchlist and wait for a better entry or a cleaner catalyst."
            parts.append(final)
            return ' '.join(parts)

        verdict = build_verdict(ticker, price, prev_close, day_pct, vol_ratio, pe, range_pct, week52_high, week52_low, price_history)

        # StockZone community activity
        all_picks   = DailyPick.objects.filter(ticker=ticker)
        sz_total    = all_picks.count()
        sz_up       = all_picks.filter(direction='UP').count()
        sz_resolved = all_picks.filter(result__in=['WIN', 'LOSS'])
        sz_res_cnt  = sz_resolved.count()
        sz_wins     = sz_resolved.filter(result='WIN').count()

        sz_up_pct   = round(sz_up / sz_total * 100) if sz_total else None
        sz_win_rate = round(sz_wins / sz_res_cnt * 100, 1) if sz_res_cnt else None

        return render(request, 'core/stock_detail.html', {
            'ticker':          ticker,
            'name':            info.get('shortName', ticker),
            'sector':          info.get('sector', '') or info.get('category', ''),
            'price':           round(float(price), 2),
            'day_pct':         day_pct,
            'prev_close':      round(float(prev_close), 2) if prev_close else None,
            'week52_high':     round(float(week52_high), 2) if week52_high else None,
            'week52_low':      round(float(week52_low), 2) if week52_low else None,
            'volume_fmt':      fmt_vol(volume),
            'avg_volume_fmt':  fmt_vol(avg_volume),
            'market_cap_fmt':  fmt_large(market_cap),
            'pe':              round(float(pe), 1) if pe else None,
            'range_pct':       range_pct,
            'chart_labels':    json.dumps(chart_labels),
            'chart_data':      json.dumps(chart_data),
            'news':            news,
            'verdict':         verdict,
            'sz_total':        sz_total,
            'sz_up_pct':       sz_up_pct,
            'sz_down_pct':     (100 - sz_up_pct) if sz_up_pct is not None else None,
            'sz_win_rate':     sz_win_rate,
            'ticker_stocks':   get_top_stocks_by_sector(),
        })

    except Exception:
        messages.error(request, f'Could not load data for "{ticker}". Check the ticker and try again.')
        return redirect('dashboard')


@login_required
def stock_chart_json(request, ticker):
    ticker = ticker.upper().strip()
    period_map = {'1w': '5d', '1m': '1mo', '3m': '3mo', '1y': '1y'}
    yf_period  = period_map.get(request.GET.get('period', '1m'), '1mo')
    try:
        hist = yf.Ticker(ticker).history(period=yf_period)
        labels, data = [], []
        for dt, row in hist.iterrows():
            labels.append(dt.strftime('%m/%d'))
            data.append(round(float(row['Close']), 2))
        return JsonResponse({'labels': labels, 'data': data})
    except Exception:
        return JsonResponse({'labels': [], 'data': []}, status=400)


def share_parlay(request, parlay_id):
    parlay = get_object_or_404(Parlay, id=parlay_id)
    legs = parlay.legs.all()
    return render(request, "core/share_parlay.html", {
        "parlay": parlay,
        "legs": legs,
    })


def share_streak(request, username):
    target = get_object_or_404(User, username=username)
    profile, _ = UserProfile.objects.get_or_create(user=target)
    return render(request, "core/share_streak.html", {
        "profile_user": target,
        "profile": profile,
    })
