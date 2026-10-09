import uuid

import django.core.validators
import django.db.models.deletion
from django.conf import settings
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

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

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
        migrations.CreateModel(
            name="Server",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "deleted_at",
                    models.DateTimeField(blank=True, db_index=True, null=True),
                ),
                ("name", models.CharField(max_length=100)),
                ("host", models.CharField(max_length=255)),
                (
                    "port",
                    models.PositiveIntegerField(
                        default=22,
                        validators=[
                            django.core.validators.MinValueValidator(1),
                            django.core.validators.MaxValueValidator(65535),
                        ],
                    ),
                ),
                ("username", models.CharField(max_length=64)),
                (
                    "auth_method",
                    models.CharField(
                        choices=[("key", "Private key"), ("password", "Password")],
                        max_length=16,
                    ),
                ),
                ("private_key_sealed", models.BinaryField(null=True)),
                ("key_passphrase_sealed", models.BinaryField(null=True)),
                ("password_sealed", models.BinaryField(null=True)),
                ("host_key", models.TextField()),
                ("host_key_fingerprint", models.CharField(max_length=100)),
                ("project_dir", models.CharField(blank=True, max_length=512)),
                ("python_path", models.CharField(default="python3", max_length=512)),
                ("manage_path", models.CharField(default="manage.py", max_length=255)),
                ("settings_module", models.CharField(blank=True, max_length=200)),
                (
                    "remote_backup_dir",
                    models.CharField(default="/var/backups/dbs", max_length=512),
                ),
                ("backup_passphrase_sealed", models.BinaryField(null=True)),
                ("file_roots", models.JSONField(blank=True, default=list)),
                ("env_path", models.CharField(blank=True, max_length=512)),
                (
                    "last_check_status",
                    models.CharField(
                        choices=[
                            ("unknown", "Not checked"),
                            ("ok", "Ready"),
                            ("problem", "Needs attention"),
                            ("failed", "Could not connect"),
                        ],
                        default="unknown",
                        max_length=16,
                    ),
                ),
                ("last_check_error", models.CharField(blank=True, max_length=64)),
                ("last_checked_at", models.DateTimeField(blank=True, null=True)),
                ("last_check_report", models.JSONField(blank=True, default=dict)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
                "abstract": False,
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(("deleted_at__isnull", True)),
                        fields=("name",),
                        name="dbs_manager_server_unique_active_name",
                    )
                ],
            },
        ),
        migrations.RunPython(seed_scheduled_tasks, migrations.RunPython.noop),
    ]
