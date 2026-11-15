from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("ledger", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="account",
            name="currency",
            field=models.CharField(blank=True, default="", max_length=3),
        ),
    ]
