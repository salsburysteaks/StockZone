from django.db import migrations, models
from decimal import Decimal


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0005_parlay_wager_payout'),
    ]

    operations = [
        migrations.AddField(
            model_name='parlayleg',
            name='odds',
            field=models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('1.50')),
        ),
    ]
