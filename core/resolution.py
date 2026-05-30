import datetime
from collections import defaultdict
from decimal import Decimal
from django.utils import timezone
import yfinance as yf

from .models import DailyPick, Parlay, ParlayLeg, FutureBet, UserProfile, PaperPortfolio, Notification


def _fetch_closes(tickers, period="5d"):
    """Return {ticker: list_of_closes} with at least the last two closes."""
    if not tickers:
        return {}
    raw = yf.download(list(tickers), period=period, auto_adjust=True, progress=False)["Close"]
    if raw.ndim == 1:
        raw = raw.to_frame(name=list(tickers)[0])
    result = {}
    for t in tickers:
        try:
            closes = raw[t].dropna().tolist()
            result[t] = closes
        except Exception:
            result[t] = []
    return result


def _direction_from_closes(closes):
    """Return 'UP', 'DOWN', or None if insufficient data."""
    if len(closes) < 2:
        return None
    return "UP" if closes[-1] > closes[-2] else "DOWN"


def _update_profiles(user_results, today):
    """
    user_results: {user: [True/False, ...]} — resolved pick outcomes per user.
    Applies day-level streak logic:
      - Gap since last pick → reset streak first.
      - At least one WIN today → increment streak.
      - All LOSS today → reset streak to 0.
      - Update longest_streak if exceeded.
      - Record last_pick_date.
    """
    yesterday = today - datetime.timedelta(days=1)
    for user, results in user_results.items():
        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.total_picks += len(results)
        profile.total_wins += sum(results)

        # Reset streak if there was a gap (missed yesterday and haven't picked today yet)
        if profile.last_pick_date and profile.last_pick_date < yesterday:
            profile.current_streak = 0

        if any(results):          # at least one correct pick
            profile.current_streak += 1
        else:                     # all picks lost
            profile.current_streak = 0

        if profile.current_streak > profile.longest_streak:
            profile.longest_streak = profile.current_streak

        profile.last_pick_date = today
        profile.save()


def _add_to_balance(user, amount):
    paper, _ = PaperPortfolio.objects.get_or_create(user=user, defaults={"balance": Decimal("10000")})
    paper.balance += amount
    paper.save()


def resolve_all(log=print):
    now = timezone.now()
    today = now.date()

    # ── Daily Picks ──────────────────────────────────────────────────────────
    pending_picks = list(
        DailyPick.objects.filter(result="PENDING").select_related("user")
    )
    tickers_needed = {p.ticker for p in pending_picks}
    closes = _fetch_closes(tickers_needed)

    picks_resolved = 0
    user_results = defaultdict(list)
    for pick in pending_picks:
        direction = _direction_from_closes(closes.get(pick.ticker, []))
        if direction is None:
            log(f"  [SKIP] {pick.ticker} — not enough price data")
            continue
        won = direction == pick.direction
        pick.result = "WIN" if won else "LOSS"
        pick.resolved_at = now
        pick.save()
        user_results[pick.user].append(won)
        picks_resolved += 1

        if won:
            notif_msg = f"Your {pick.direction} pick on {pick.ticker} hit — you won!"
        else:
            notif_msg = f"Your {pick.direction} pick on {pick.ticker} missed — better luck next time"
        Notification.objects.create(user=pick.user, message=notif_msg, notification_type="pick_resolved")

    _update_profiles(user_results, today)
    log(f"Daily picks resolved: {picks_resolved} / {len(pending_picks)}")

    # ── Parlays ───────────────────────────────────────────────────────────────
    pending_parlays = list(
        Parlay.objects.filter(result="PENDING").prefetch_related("legs__parlay__user").select_related("user")
    )
    all_leg_tickers = {leg.ticker for p in pending_parlays for leg in p.legs.all()}
    leg_closes = _fetch_closes(all_leg_tickers)

    parlays_resolved = 0
    for parlay in pending_parlays:
        legs = list(parlay.legs.all())
        all_resolved = True
        all_won = True

        for leg in legs:
            if leg.price_at_pick is not None:
                # Use price_at_pick for legs that have it
                lc = leg_closes.get(leg.ticker, [])
                if not lc:
                    all_resolved = False
                    continue
                current = lc[-1]
                moved_up = current > float(leg.price_at_pick)
                won = (leg.direction == "UP") == moved_up
            else:
                # Fall back to prev-close vs current-close direction
                direction = _direction_from_closes(leg_closes.get(leg.ticker, []))
                if direction is None:
                    all_resolved = False
                    continue
                won = direction == leg.direction

            leg.result = "WIN" if won else "LOSS"
            leg.save()
            if not won:
                all_won = False

        if not all_resolved:
            log(f"  [SKIP] Parlay {parlay.id} — missing price data for one or more legs")
            continue

        parlay.result = "WIN" if all_won else "LOSS"
        if parlay.payout_multiplier <= Decimal("1.0"):
            parlay.payout_multiplier = Decimal(str(parlay.calculate_multiplier()))

        if all_won and parlay.wager > 0:
            payout = (parlay.wager * parlay.payout_multiplier).quantize(Decimal("0.01"))
            parlay.payout = payout
            parlay.save()
            _add_to_balance(parlay.user, payout)
            notif_msg = f"Your {len(legs)}-leg parlay won! Payout: ${payout}"
        else:
            parlay.payout = Decimal("0.00")
            parlay.save()
            if all_won:
                notif_msg = f"Your {len(legs)}-leg parlay won!"
            else:
                notif_msg = f"Your {len(legs)}-leg parlay missed — one or more legs didn't hit"
        Notification.objects.create(user=parlay.user, message=notif_msg, notification_type="parlay_resolved")

        parlays_resolved += 1

    log(f"Parlays resolved: {parlays_resolved} / {len(pending_parlays)}")

    # ── Future Bets ───────────────────────────────────────────────────────────
    due_bets = list(
        FutureBet.objects.filter(result="PENDING", resolves_at__lte=today).select_related("user")
    )
    bet_tickers = {b.ticker for b in due_bets}
    bet_closes = _fetch_closes(bet_tickers)

    bets_resolved = 0
    for bet in due_bets:
        lc = bet_closes.get(bet.ticker, [])
        if not lc:
            log(f"  [SKIP] FutureBet {bet.id} ({bet.ticker}) — no price data")
            continue

        current = lc[-1]
        if bet.price_at_pick is not None:
            moved_up = current > float(bet.price_at_pick)
        else:
            if len(lc) < 2:
                log(f"  [SKIP] FutureBet {bet.id} ({bet.ticker}) — not enough closes")
                continue
            moved_up = lc[-1] > lc[-2]

        won = (bet.direction == "UP") == moved_up
        bet.result = "WIN" if won else "LOSS"
        bet.resolved_at = now

        if won:
            payout = (bet.wager * bet.daily_odds_multiplier).quantize(Decimal("0.01"))
            bet.payout = payout
            bet.save()
            _add_to_balance(bet.user, payout)
        else:
            bet.payout = Decimal("0.00")
            bet.save()

        bets_resolved += 1

    log(f"Future bets resolved: {bets_resolved} / {len(due_bets)}")

    return picks_resolved, parlays_resolved, bets_resolved
