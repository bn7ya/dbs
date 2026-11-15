import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dbs", "0005_pull_only_retention_chain"),
    ]

    operations = [
        migrations.AlterField(
            model_name="backupschedule",
            name="keep",
            field=models.PositiveIntegerField(
                default=5,
                validators=[
                    django.core.validators.MinValueValidator(1),
                    django.core.validators.MaxValueValidator(10000),
                ],
            ),
        ),
    ]
