from django.db import migrations, models
from django.utils import timezone

SCHEDULED_TASKS = ("sweep_stale_jobs",)


def seed_scheduled_tasks(apps, schema_editor):
    ScheduledTask = apps.get_model("dbs_manager", "ScheduledTask")
    now = timezone.now()
    for name in SCHEDULED_TASKS:
        ScheduledTask.objects.get_or_create(name=name, defaults={"next_run_at": now})


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="ScheduledTask",
            fields=[
                (
                    "name",
                    models.CharField(max_length=64, primary_key=True, serialize=False),
                ),
                ("next_run_at", models.DateTimeField()),
            ],
            options={
                "ordering": ("next_run_at", "name"),
            },
        ),
        migrations.RunPython(seed_scheduled_tasks, migrations.RunPython.noop),
    ]
