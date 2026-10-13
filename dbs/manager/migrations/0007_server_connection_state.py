from django.db import migrations, models
from django.utils import timezone

PROBE_TASK = "probe_servers"


def seed_probe_task(apps, schema_editor):
    ScheduledTask = apps.get_model("dbs_manager", "ScheduledTask")
    ScheduledTask.objects.get_or_create(
        name=PROBE_TASK, defaults={"next_run_at": timezone.now()}
    )


def drop_probe_task(apps, schema_editor):
    ScheduledTask = apps.get_model("dbs_manager", "ScheduledTask")
    ScheduledTask.objects.filter(name=PROBE_TASK).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("dbs_manager", "0006_plan_retention_limits"),
    ]

    operations = [
        migrations.AddField(
            model_name="server",
            name="connection_state",
            field=models.CharField(
                choices=[
                    ("unknown", "Not seen yet"),
                    ("online", "Online"),
                    ("offline", "Offline"),
                ],
                default="unknown",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="server",
            name="last_connection_error",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="server",
            name="last_seen_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="server",
            name="timeout_in_container",
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="server",
            name="timeout_on_host",
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.RunPython(seed_probe_task, drop_probe_task),
    ]
