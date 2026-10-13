import django.core.validators
from django.db import migrations, models

KEEP_MIN = 1
KEEP_MAX = 5


def clamp_retention(apps, schema_editor):
    plans = apps.get_model("dbs_manager", "BackupPlan")._base_manager
    plans.filter(keep__gt=KEEP_MAX).update(keep=KEEP_MAX)
    plans.filter(keep__lt=KEEP_MIN).update(keep=KEEP_MIN)
    plans.filter(keep_remote__gt=KEEP_MAX).update(keep_remote=KEEP_MAX)


class Migration(migrations.Migration):
    dependencies = [
        ("dbs_manager", "0003_server_runtime"),
    ]

    operations = [
        migrations.AlterField(
            model_name="backupplan",
            name="keep",
            field=models.PositiveSmallIntegerField(
                default=5,
                validators=[
                    django.core.validators.MinValueValidator(1),
                    django.core.validators.MaxValueValidator(5),
                ],
            ),
        ),
        migrations.AlterField(
            model_name="backupplan",
            name="keep_remote",
            field=models.PositiveSmallIntegerField(
                default=0,
                validators=[
                    django.core.validators.MinValueValidator(0),
                    django.core.validators.MaxValueValidator(5),
                ],
            ),
        ),
        migrations.RunPython(clamp_retention, migrations.RunPython.noop),
    ]
