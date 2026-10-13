from django.db import migrations
from django.utils import timezone

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
    ]
