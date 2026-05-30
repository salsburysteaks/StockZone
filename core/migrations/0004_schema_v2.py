from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_futurebet_parlay_parlayleg_userprofile'),
    ]

    operations = [
        # ── UserProfile ───────────────────────────────────────────────────────
        migrations.RenameField('UserProfile', 'streak', 'current_streak'),
        migrations.AddField(
            model_name='UserProfile',
            name='longest_streak',
            field=models.IntegerField(default=0),
        ),

        # ── Parlay ────────────────────────────────────────────────────────────
        migrations.RenameField('Parlay', 'status', 'result'),
        migrations.AddField(
            model_name='Parlay',
            name='payout_multiplier',
            field=models.DecimalField(decimal_places=4, default=1.0, max_digits=8),
        ),

        # ── ParlayLeg ─────────────────────────────────────────────────────────
        migrations.AddField(
            model_name='ParlayLeg',
            name='price_at_pick',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True),
        ),

        # ── FutureBet ─────────────────────────────────────────────────────────
        migrations.RenameField('FutureBet', 'entry_price', 'price_at_pick'),
        migrations.AddField(
            model_name='FutureBet',
            name='wager',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10),
        ),
        migrations.AddField(
            model_name='FutureBet',
            name='payout',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True),
        ),
    ]
