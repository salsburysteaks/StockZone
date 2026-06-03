from datetime import datetime, timedelta
import yfinance as yf
from django.core.cache import cache

SECTOR_TICKERS = {
    "Technology": ["AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMD", "INTC", "CRM", "AVGO", "QCOM", "TXN", "ADBE", "MU", "AMAT", "ORCL"],
    "Healthcare": ["JNJ", "UNH", "PFE", "ABBV", "MRK", "TMO", "ABT", "LLY", "DHR", "BMY", "AMGN", "GILD", "CVS", "CI", "HUM"],
    "Finance":    ["JPM", "BAC", "WFC", "GS", "MS", "C", "BLK", "AXP", "USB", "PNC", "TFC", "COF", "SCHW", "MET", "PRU"],
    "Energy":     ["XOM", "CVX", "COP", "EOG", "SLB", "MPC", "PSX", "VLO", "OXY", "HAL", "DVN", "HES", "MRO", "BKR", "CTRA"],
    "Consumer":   ["WMT", "HD", "PG", "KO", "PEP", "COST", "TGT", "MCD", "NKE", "SBUX", "LOW", "DG", "DLTR", "CL", "PM"],
}

COMPANY_NAMES = {
    # Technology
    "AAPL": "Apple Inc.", "MSFT": "Microsoft Corp.", "NVDA": "NVIDIA Corp.",
    "GOOGL": "Alphabet Inc.", "META": "Meta Platforms", "AMD": "Advanced Micro Devices",
    "INTC": "Intel Corp.", "CRM": "Salesforce Inc.", "AVGO": "Broadcom Inc.",
    "QCOM": "Qualcomm Inc.", "TXN": "Texas Instruments", "ADBE": "Adobe Inc.",
    "MU": "Micron Technology", "AMAT": "Applied Materials", "ORCL": "Oracle Corp.",
    # Healthcare
    "JNJ": "Johnson & Johnson", "UNH": "UnitedHealth Group", "PFE": "Pfizer Inc.",
    "ABBV": "AbbVie Inc.", "MRK": "Merck & Co.", "TMO": "Thermo Fisher Scientific",
    "ABT": "Abbott Laboratories", "LLY": "Eli Lilly & Co.", "DHR": "Danaher Corp.",
    "BMY": "Bristol-Myers Squibb", "AMGN": "Amgen Inc.", "GILD": "Gilead Sciences",
    "CVS": "CVS Health Corp.", "CI": "Cigna Group", "HUM": "Humana Inc.",
    # Finance
    "JPM": "JPMorgan Chase", "BAC": "Bank of America", "WFC": "Wells Fargo",
    "GS": "Goldman Sachs", "MS": "Morgan Stanley", "C": "Citigroup Inc.",
    "BLK": "BlackRock Inc.", "AXP": "American Express", "USB": "U.S. Bancorp",
    "PNC": "PNC Financial", "TFC": "Truist Financial", "COF": "Capital One",
    "SCHW": "Charles Schwab", "MET": "MetLife Inc.", "PRU": "Prudential Financial",
    # Energy
    "XOM": "Exxon Mobil Corp.", "CVX": "Chevron Corp.", "COP": "ConocoPhillips",
    "EOG": "EOG Resources", "SLB": "SLB (Schlumberger)", "MPC": "Marathon Petroleum",
    "PSX": "Phillips 66", "VLO": "Valero Energy", "OXY": "Occidental Petroleum",
    "HAL": "Halliburton Co.", "DVN": "Devon Energy", "HES": "Hess Corp.",
    "MRO": "Marathon Oil", "BKR": "Baker Hughes", "CTRA": "Coterra Energy",
    # Consumer
    "WMT": "Walmart Inc.", "HD": "Home Depot", "PG": "Procter & Gamble",
    "KO": "Coca-Cola Co.", "PEP": "PepsiCo Inc.", "COST": "Costco Wholesale",
    "TGT": "Target Corp.", "MCD": "McDonald's Corp.", "NKE": "Nike Inc.",
    "SBUX": "Starbucks Corp.", "LOW": "Lowe's Companies", "DG": "Dollar General",
    "DLTR": "Dollar Tree", "CL": "Colgate-Palmolive", "PM": "Philip Morris",
}

# (scale_factor, floor_minimum) per timeframe
TIMEFRAME_FACTORS = {
    "3D": (1.5, 2.0),
    "1W": (2.2, 3.0),
    "2W": (3.5, 5.0),
    "1M": (6.0, 10.0),
}


def _fmt_volume(v):
    if v >= 1_000_000_000:
        return f"{v / 1_000_000_000:.1f}B"
    if v >= 1_000_000:
        return f"{v / 1_000_000:.1f}M"
    if v >= 1_000:
        return f"{v / 1_000:.1f}K"
    return str(v)


def _calc_odds(momentum, realized_vol, vol_spike, direction):
    base = 1.1 + (realized_vol * 0.08)
    base = max(1.1, min(base, 2.8))

    if vol_spike > 2.0:
        base *= 1.2
    elif vol_spike > 1.5:
        base *= 1.1

    if momentum > 0 and direction == "UP":
        odds = base * 0.8
    elif momentum > 0 and direction == "DOWN":
        odds = base * 1.3
    elif momentum < 0 and direction == "DOWN":
        odds = base * 0.8
    elif momentum < 0 and direction == "UP":
        odds = base * 1.3
    else:
        odds = base

    return round(max(1.05, min(odds, 4.0)), 2)


def calculate_future_odds(realized_vol, timeframe):
    """Return payout multiplier for a future bet: realized_vol × factor, floored at minimum."""
    factor, minimum = TIMEFRAME_FACTORS.get(timeframe, (2.2, 3.0))
    return round(max(minimum, min(realized_vol * factor, 20.0)), 2)


def get_top_stocks_by_sector(top_n=5):
    cached = cache.get('top_stocks')
    if cached is not None:
        return cached

    end   = datetime.today()
    start = end - timedelta(days=7)

    all_results = []

    for sector, tickers in SECTOR_TICKERS.items():
        raw = yf.download(
            tickers,
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            auto_adjust=True,
            progress=False,
        )

        close  = raw["Close"]
        volume = raw["Volume"]

        if close.ndim == 1:
            close  = close.to_frame(name=tickers[0])
            volume = volume.to_frame(name=tickers[0])

        sector_stocks = []
        for ticker in tickers:
            try:
                cs = close[ticker].dropna()
                vs = volume[ticker].dropna()
                if len(cs) < 2:
                    continue

                price_now   = float(cs.iloc[-1])
                price_prev  = float(cs.iloc[-2])
                momentum    = round((price_now - price_prev) / price_prev * 100, 2)
                week52_high = round(float(cs.max()), 2)
                vol_raw     = int(vs.iloc[-1]) if len(vs) else 0

                returns      = cs.pct_change().dropna().tail(5)
                realized_vol = float(returns.std() * 100) if len(returns) >= 2 else 1.0

                avg_volume = float(vs.tail(5).mean()) if len(vs) >= 5 else float(vs.mean())
                vol_spike  = float(vs.iloc[-1]) / avg_volume if avg_volume > 0 else 1.0

                odds_up   = _calc_odds(momentum, realized_vol, vol_spike, "UP")
                odds_down = _calc_odds(momentum, realized_vol, vol_spike, "DOWN")

                future_odds = {
                    tf: calculate_future_odds(realized_vol, tf)
                    for tf in TIMEFRAME_FACTORS
                }

                sector_stocks.append({
                    "ticker":       ticker,
                    "company_name": COMPANY_NAMES.get(ticker, ticker),
                    "sector":       sector,
                    "price":        round(price_now, 2),
                    "prev_close":   round(price_prev, 2),
                    "momentum":     momentum,
                    "week52_high":  week52_high,
                    "volume":       _fmt_volume(vol_raw),
                    "realized_vol": round(realized_vol, 2),
                    "vol_spike":    round(vol_spike, 2),
                    "odds_up":      odds_up,
                    "odds_down":    odds_down,
                    "future_odds":  future_odds,
                })
            except Exception:
                continue

        sector_stocks.sort(key=lambda x: x["momentum"], reverse=True)
        all_results.extend(sector_stocks[:top_n])

    # Overlay live price and momentum for the displayed tickers only
    for stock in all_results:
        try:
            info = yf.Ticker(stock["ticker"]).fast_info
            live_price = info.last_price
            prev_close = info.previous_close
            if live_price and prev_close and prev_close > 0:
                stock["price"]      = round(float(live_price), 2)
                stock["prev_close"] = round(float(prev_close), 2)
                stock["momentum"]   = round(((live_price - prev_close) / prev_close) * 100, 2)
        except Exception:
            pass

    cache.set('top_stocks', all_results, timeout=55)
    return all_results
