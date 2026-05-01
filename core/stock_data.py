import yfinance as yf
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

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


def _fmt_volume(v):
    if v >= 1_000_000_000:
        return f"{v / 1_000_000_000:.1f}B"
    if v >= 1_000_000:
        return f"{v / 1_000_000:.1f}M"
    if v >= 1_000:
        return f"{v / 1_000:.1f}K"
    return str(v)


def _fetch_pe(ticker):
    try:
        pe = yf.Ticker(ticker).info.get("trailingPE")
        return ticker, round(float(pe), 1) if pe else None
    except Exception:
        return ticker, None


def get_top_stocks_by_sector(top_n=5):
    end   = datetime.today()
    start = end - timedelta(days=400)  # ~1 year + buffer for trading days

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
                price_30d   = float(cs.iloc[-22]) if len(cs) >= 22 else float(cs.iloc[0])
                momentum    = round((price_now - price_30d) / price_30d * 100, 2)
                week52_high = round(float(cs.max()), 2)
                vol_raw     = int(vs.iloc[-1]) if len(vs) else 0
                sector_stocks.append({
                    "ticker":       ticker,
                    "company_name": COMPANY_NAMES.get(ticker, ticker),
                    "sector":       sector,
                    "price":        round(price_now, 2),
                    "momentum":     momentum,
                    "week52_high":  week52_high,
                    "volume":       _fmt_volume(vol_raw),
                    "pe_ratio":     None,
                })
            except Exception:
                continue

        sector_stocks.sort(key=lambda x: x["momentum"], reverse=True)
        all_results.extend(sector_stocks[:top_n])

    # Parallel PE fetch for all 25 selected stocks at once
    ticker_map = {s["ticker"]: s for s in all_results}
    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = {ex.submit(_fetch_pe, t): t for t in ticker_map}
        for future in as_completed(futures):
            ticker, pe = future.result()
            ticker_map[ticker]["pe_ratio"] = pe

    return all_results
