import django.core.validators
from django.db import migrations, models
from django.utils import timezone

MAXIMUM_KEEP = 5
TARGET_REMOVED = "target.remove"
TARGET_REMOVED_DETAIL = (
    "This server no longer pushes backups anywhere. The DBS manager pulls them: "
    "add this server to it with `django_dbs server add`."
)


def record_removed_targets(apps, schema_editor):
    alias = schema_editor.connection.alias
    BackupTarget = apps.get_model("dbs", "BackupTarget")
    AuditEvent = apps.get_model("dbs", "AuditEvent")
    now = timezone.now()
    for target in BackupTarget.objects.using(alias).order_by("name"):
        AuditEvent.objects.using(alias).create(
            action=TARGET_REMOVED,
            target_name=target.name,
            detail=TARGET_REMOVED_DETAIL,
            data={
                "host": target.host,
                "port": target.port,
                "username": target.username,
                "remote_dir": target.remote_dir,
            },
            status="succeeded",
            succeeded=True,
            started_at=now,
            finished_at=now,
        )


def keep_at_most_five(apps, schema_editor):
    BackupSchedule = apps.get_model("dbs", "BackupSchedule")
    schedules = BackupSchedule.objects.using(schema_editor.connection.alias)
    schedules.filter(keep__gt=MAXIMUM_KEEP).update(keep=MAXIMUM_KEEP)
    schedules.filter(keep__lt=1).update(keep=1)


class Migration(migrations.Migration):

    dependencies = [
        ("dbs", "0004_schedule_lease"),
    ]

    operations = [
        migrations.RunPython(record_removed_targets, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="backupschedule",
            name="push_target",
        ),
        migrations.RemoveField(
            model_name="backupschedule",
            name="keep_remote",
        ),
        migrations.RemoveField(
            model_name="backuprecord",
            name="target",
        ),
        migrations.DeleteModel(
            name="BackupTarget",
        ),
        migrations.AlterField(
            model_name="backupschedule",
            name="keep",
            field=models.PositiveIntegerField(
                default=5,
                validators=[
                    django.core.validators.MinValueValidator(1),
                    django.core.validators.MaxValueValidator(5),
                ],
            ),
        ),
        migrations.RunPython(keep_at_most_five, migrations.RunPython.noop),
    ]
