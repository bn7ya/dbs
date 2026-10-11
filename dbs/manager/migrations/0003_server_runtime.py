from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("dbs_manager", "0002_cache_table"),
    ]

    operations = [
        migrations.AddField(
            model_name="server",
            name="compose_files",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="server",
            name="compose_service",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name="server",
            name="runtime",
            field=models.CharField(
                choices=[
                    ("host", "On the server"),
                    ("compose", "In a Docker Compose service"),
                ],
                default="host",
                max_length=16,
            ),
        ),
    ]
