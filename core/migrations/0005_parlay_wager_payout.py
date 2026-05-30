from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0004_schema_v2'),
    ]

    operations = [
        migrations.AddField(
            model_name='Parlay',
            name='wager',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10),
        ),
        migrations.AddField(
            model_name='Parlay',
            name='payout',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True),
        ),
    ]
