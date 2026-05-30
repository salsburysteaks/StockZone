from django.db import migrations, models
from decimal import Decimal


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0006_parlayleg_odds'),
    ]

    operations = [
        migrations.AddField(
            model_name='futurebet',
            name='daily_odds_multiplier',
            field=models.DecimalField(max_digits=6, decimal_places=2, default=Decimal('2.00')),
        ),
    ]
