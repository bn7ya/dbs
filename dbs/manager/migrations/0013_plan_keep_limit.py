import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("dbs_manager", "0012_application_deployment"),
    ]

    operations = [
        migrations.AlterField(
            model_name="backupplan",
            name="keep",
            field=models.PositiveSmallIntegerField(
                default=5,
                validators=[
                    django.core.validators.MinValueValidator(1),
                    django.core.validators.MaxValueValidator(10000),
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
                    django.core.validators.MaxValueValidator(10000),
                ],
            ),
        ),
    ]
