from django.core.management.base import BaseCommand
from django.utils import timezone
from groq import Groq
import os

from core.stock_data import get_top_stocks_by_sector
from core.models import BullishPick


class Command(BaseCommand):
    help = "Generate Bullish's Pick of the Day via Groq — run once daily at market open."

    def handle(self, *args, **options):
        today = timezone.localdate()

        if BullishPick.objects.filter(date=today).exists():
            self.stdout.write(self.style.WARNING(f"Pick already exists for {today}. Skipping."))
            return

        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            self.stderr.write("GROQ_API_KEY not set. Aborting.")
            return

        self.stdout.write("Fetching top movers...")
        stocks = get_top_stocks_by_sector()
        if not stocks:
            self.stderr.write("No stock data returned. Aborting.")
            return

        # Score by combined momentum strength and volume spike
        def score(s):
            return abs(s.get("momentum", 0)) * s.get("vol_spike", 1.0)

        best = max(stocks, key=score)

        ticker       = best["ticker"]
        company_name = best["company_name"]
        sector       = best.get("sector", "")
        price        = best["price"]
        momentum     = best["momentum"]
        vol_spike    = best.get("vol_spike", 1.0)
        direction_hint = "UP" if momentum >= 0 else "DOWN"

        self.stdout.write(f"Selected {ticker} (momentum {momentum:+.2f}%, vol spike {vol_spike:.2f}x). Calling Groq...")

        prompt = (
            f"You are Bullish, the StockZone AI analyst. Today's setup: {ticker} ({company_name}) "
            f"at ${price}, {momentum:+.2f}% today, volume {vol_spike:.1f}x the average.\n\n"
            f"Write a Pick of the Day. First line must be exactly 'DIRECTION: UP' or 'DIRECTION: DOWN'. "
            f"Then 3 sentences: why you like this setup today, what the key risk is, and what would change your mind. "
            f"Be direct and confident. No hyphens. No filler phrases like certainly or great question."
        )

        client = Groq(api_key=api_key)
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are Bullish, the StockZone Assistant. You are a sharp confident stock analyst "
                        "who talks like a real person. Never use hyphens. Never say certainly or great question."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=250,
        )

        raw = response.choices[0].message.content.strip()

        # Parse direction from first line
        lines = [l.strip() for l in raw.splitlines() if l.strip()]
        direction = direction_hint
        reasoning_lines = lines

        if lines and lines[0].upper().startswith("DIRECTION:"):
            dir_word = lines[0].split(":", 1)[1].strip().upper()
            if "UP" in dir_word:
                direction = "UP"
            elif "DOWN" in dir_word:
                direction = "DOWN"
            reasoning_lines = lines[1:]

        reasoning = " ".join(reasoning_lines).strip()
        if not reasoning:
            reasoning = raw

        pick = BullishPick.objects.create(
            ticker=ticker,
            company_name=company_name,
            sector=sector,
            direction=direction,
            reasoning=reasoning,
            price=price,
            momentum=momentum,
            date=today,
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Pick of the Day saved: {ticker} {direction} — {reasoning[:80]}..."
            )
        )
