import uuid

import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.utils import timezone

SCHEDULED_TASKS = (
    "dispatch_due_plans",
    "remove_expired_files",
    "snapshot_env_files",
    "sweep_stale_jobs",
)


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
            },
        ),
        migrations.CreateModel(
            name="EnvVersion",
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
                ("path", models.CharField(max_length=1024)),
                ("content_sealed", models.BinaryField()),
                ("fingerprint", models.CharField(max_length=64)),
                ("size", models.PositiveIntegerField()),
                ("key_names", models.JSONField(blank=True, default=list)),
                (
                    "source",
                    models.CharField(
                        choices=[
                            ("pulled", "Pulled"),
                            ("pushed", "Pushed"),
                            ("scheduled", "Scheduled"),
                        ],
                        max_length=16,
                    ),
                ),
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
                (
                    "server",
                    models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="dbs_manager.server",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="BackupPlan",
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
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("dbs", "django-dbs backup"),
                            ("archive", "Archive of server folders"),
                            ("collect", "Files a server already makes"),
                        ],
                        max_length=16,
                    ),
                ),
                ("paths", models.JSONField(blank=True, default=list)),
                ("pattern", models.CharField(blank=True, default="", max_length=200)),
                (
                    "interval_minutes",
                    models.PositiveIntegerField(blank=True, null=True),
                ),
                (
                    "keep",
                    models.PositiveSmallIntegerField(
                        default=7,
                        validators=[
                            django.core.validators.MinValueValidator(1),
                            django.core.validators.MaxValueValidator(365),
                        ],
                    ),
                ),
                (
                    "keep_remote",
                    models.PositiveSmallIntegerField(
                        default=1,
                        validators=[django.core.validators.MaxValueValidator(365)],
                    ),
                ),
                ("enabled", models.BooleanField(default=True)),
                ("next_run_at", models.DateTimeField(blank=True, null=True)),
                ("last_run_at", models.DateTimeField(blank=True, null=True)),
                (
                    "last_status",
                    models.CharField(
                        choices=[
                            ("none", "Not run yet"),
                            ("succeeded", "Succeeded"),
                            ("failed", "Failed"),
                        ],
                        default="none",
                        max_length=16,
                    ),
                ),
                ("last_error_code", models.CharField(blank=True, max_length=64)),
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
                (
                    "server",
                    models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="dbs_manager.server",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
                "abstract": False,
            },
        ),
        migrations.CreateModel(
            name="BackupFile",
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
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("dbs", "django-dbs backup"),
                            ("archive", "Archive of server folders"),
                            ("collected", "File collected from a server folder"),
                            ("uploaded", "File uploaded from a browser"),
                        ],
                        max_length=16,
                    ),
                ),
                ("name", models.CharField(max_length=255)),
                ("size", models.PositiveBigIntegerField()),
                ("sha256", models.CharField(max_length=64)),
                ("storage_path", models.CharField(max_length=512)),
                ("sealed", models.BooleanField(default=False)),
                (
                    "validation",
                    models.CharField(
                        choices=[
                            ("structure_ok", "Structure checked"),
                            ("verified", "Verified"),
                            ("failed", "Failed"),
                        ],
                        max_length=16,
                    ),
                ),
                ("validated_at", models.DateTimeField(blank=True, null=True)),
                ("remote_path", models.CharField(blank=True, max_length=1024)),
                ("remote_size", models.PositiveBigIntegerField(blank=True, null=True)),
                ("remote_mtime", models.DateTimeField(blank=True, null=True)),
                ("removed_at", models.DateTimeField(blank=True, null=True)),
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
                (
                    "plan",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="dbs_manager.backupplan",
                    ),
                ),
                (
                    "server",
                    models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="dbs_manager.server",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
                "abstract": False,
            },
        ),
        migrations.AddConstraint(
            model_name="server",
            constraint=models.UniqueConstraint(
                condition=models.Q(("deleted_at__isnull", True)),
                fields=("name",),
                name="dbs_manager_server_unique_active_name",
            ),
        ),
        migrations.AddIndex(
            model_name="envversion",
            index=models.Index(
                fields=["server", "-created_at"], name="dbs_manager_env_server_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="backupplan",
            index=models.Index(
                fields=["enabled", "next_run_at"], name="dbs_manager_plan_due_idx"
            ),
        ),
        migrations.AddConstraint(
            model_name="backupplan",
            constraint=models.UniqueConstraint(
                condition=models.Q(("deleted_at__isnull", True)),
                fields=("server", "name"),
                name="dbs_manager_plan_unique_active_name",
            ),
        ),
        migrations.AddIndex(
            model_name="backupfile",
            index=models.Index(
                fields=["server", "-created_at"], name="dbs_manager_backup_server_idx"
            ),
        ),
        migrations.AddConstraint(
            model_name="backupfile",
            constraint=models.UniqueConstraint(
                condition=models.Q(("removed_at__isnull", True)),
                fields=("storage_path",),
                name="dbs_manager_backup_unique_stored_path",
            ),
        ),
        migrations.RunPython(seed_scheduled_tasks, migrations.RunPython.noop),
    ]
