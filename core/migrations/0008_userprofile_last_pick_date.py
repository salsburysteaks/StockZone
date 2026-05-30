from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0007_futurebet_daily_odds_multiplier"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="last_pick_date",
            field=models.DateField(blank=True, null=True),
        ),
    ]
