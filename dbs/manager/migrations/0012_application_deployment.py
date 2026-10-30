from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("dbs_manager", "0011_plan_schedule"),
    ]

    operations = [
        migrations.AddField(
            model_name="application",
            name="deployment",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
