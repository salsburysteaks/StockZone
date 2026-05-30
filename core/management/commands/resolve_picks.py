from django.core.management.base import BaseCommand
from core.resolution import resolve_all


class Command(BaseCommand):
    help = "Resolve pending daily picks, parlays, and future bets using live prices from yfinance."

    def handle(self, *args, **options):
        self.stdout.write("Resolving picks, parlays, and future bets...")
        picks, parlays, bets = resolve_all(log=self.stdout.write)
        self.stdout.write(self.style.SUCCESS(
            f"\nDone — {picks} pick(s), {parlays} parlay(s), {bets} future bet(s) resolved."
        ))
