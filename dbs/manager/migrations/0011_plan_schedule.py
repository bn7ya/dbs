from django.db import migrations, models


def anchor_where_it_runs(apps, schema_editor):
    BackupPlan = apps.get_model("dbs_manager", "BackupPlan")
    BackupPlan._base_manager.using(schema_editor.connection.alias).filter(
        anchor_at=None
    ).exclude(next_run_at=None).update(anchor_at=models.F("next_run_at"))


class Migration(migrations.Migration):
    dependencies = [
        ("dbs_manager", "0010_application_cleanup"),
    ]

    operations = [
        migrations.AddField(
            model_name="backupplan",
            name="anchor_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="backupplan",
            name="time_zone",
            field=models.CharField(default="UTC", max_length=64),
        ),
        migrations.RunPython(anchor_where_it_runs, migrations.RunPython.noop),
    ]
