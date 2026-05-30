# StockZone

## Overview

StockZone is a sportsbook-style stock picking app where users build parlays, track picks, and compete on a leaderboard using paper money — no real cash involved.

## Tech Stack

- Django
- SQLite
- yfinance
- Chart.js
- Deployed on PythonAnywhere

## Features

- Parlay builder with dynamic odds based on beta and daily price change
- Paper portfolio for buying and selling stocks with a starting balance
- Leaderboard ranked by win rate across all resolved picks
- Future bets with multiple timeframes (3 days to 1 month)
- Pick resolution via management command using live yfinance data
- Live stock data pulled on each dashboard load with a 60-second cache
- Per-stock news feed in the stock modal via yfinance
- Notification system for resolved picks and parlays

## Getting Started

```bash
git clone https://github.com/salsburysteaks/StockZone.git
cd StockZone
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

## Resolving Picks

Run the management command to settle all open picks and parlays and trigger notifications:

```bash
python manage.py resolve_picks
```

This resolves pending daily picks, parlays, and future bets using the latest closing prices from yfinance. On PythonAnywhere, schedule this as a daily task after market close.

## Notes

- Live stock data requires an internet connection. The dashboard will load stale data if yfinance is unreachable.
- Paper balance resets and user management are handled through the Django admin panel at `/admin/`.
