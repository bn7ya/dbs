from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("dbs_manager", "0003_server_runtime"),
    ]

    operations = [
        migrations.AddField(
            model_name="backupfile",
            name="failure",
            field=models.CharField(blank=True, max_length=500),
        ),
    ]
