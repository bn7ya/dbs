import django.core.validators
import django.db.models.deletion
import uuid

from django.conf import settings
from django.db import migrations, models


def created_by(**options):
    return models.ForeignKey(
        blank=True,
        null=True,
        on_delete=django.db.models.deletion.SET_NULL,
        related_name="+",
        to=settings.AUTH_USER_MODEL,
        **options,
    )


UNINDEXED = {
    "created_at": models.DateTimeField(auto_now_add=True),
    "deleted_at": models.DateTimeField(blank=True, null=True),
    "created_by": created_by(db_constraint=False, db_index=False),
}
REINDEXED = {
    "created_at": models.DateTimeField(auto_now_add=True, db_index=True),
    "deleted_at": models.DateTimeField(blank=True, db_index=True, null=True),
    "created_by": created_by(),
}


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("dbs_manager", "0007_server_connection_state"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="server", name="dbs_manager_server_unique_active_name"
        ),
        migrations.RemoveConstraint(
            model_name="backupplan", name="dbs_manager_plan_unique_active_name"
        ),
        migrations.RemoveIndex(model_name="backupfile", name="dbs_manager_backup_server_idx"),
        migrations.RemoveIndex(model_name="envversion", name="dbs_manager_env_server_idx"),
        migrations.RenameModel(old_name="Server", new_name="Application"),
        *[
            migrations.AlterField(model_name="application", name=name, field=field)
            for name, field in UNINDEXED.items()
        ],
        *[
            migrations.AlterField(model_name="application", name=name, field=field)
            for name, field in REINDEXED.items()
        ],
        migrations.RenameField(model_name="backupplan", old_name="server", new_name="application"),
        migrations.RenameField(model_name="backupfile", old_name="server", new_name="application"),
        migrations.RenameField(model_name="envversion", old_name="server", new_name="application"),
        migrations.AddConstraint(
            model_name="backupplan",
            constraint=models.UniqueConstraint(
                condition=models.Q(("deleted_at__isnull", True)),
                fields=("application", "name"),
                name="dbs_manager_plan_unique_active_name",
            ),
        ),
        migrations.AddIndex(
            model_name="backupfile",
            index=models.Index(
                fields=["application", "-created_at"], name="dbs_manager_backup_app_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="envversion",
            index=models.Index(
                fields=["application", "-created_at"], name="dbs_manager_env_app_idx"
            ),
        ),
        migrations.CreateModel(
            name="Server",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, db_index=True, null=True)),
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
                ("private_key_sealed", models.BinaryField(editable=False, null=True)),
                ("key_passphrase_sealed", models.BinaryField(editable=False, null=True)),
                ("password_sealed", models.BinaryField(editable=False, null=True)),
                ("host_key", models.TextField()),
                ("host_key_fingerprint", models.CharField(max_length=100)),
                ("engines", models.JSONField(blank=True, default=dict)),
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
                ("timeout_on_host", models.BooleanField(blank=True, null=True)),
                (
                    "connection_state",
                    models.CharField(
                        choices=[
                            ("unknown", "Not seen yet"),
                            ("online", "Online"),
                            ("offline", "Offline"),
                        ],
                        default="unknown",
                        max_length=16,
                    ),
                ),
                ("last_seen_at", models.DateTimeField(blank=True, null=True)),
                ("last_connection_error", models.CharField(blank=True, max_length=64)),
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
            options={"ordering": ["-created_at"], "abstract": False},
        ),
        migrations.AddField(
            model_name="application",
            name="server",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="applications",
                to="dbs_manager.server",
            ),
        ),
        migrations.AddField(
            model_name="application",
            name="kind",
            field=models.CharField(
                choices=[
                    ("host", "On the server"),
                    ("compose", "In a Compose service"),
                    ("container", "In a container"),
                ],
                default="host",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="application",
            name="engine",
            field=models.CharField(
                blank=True,
                choices=[("", "No container"), ("docker", "Docker"), ("podman", "Podman")],
                default="",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="application",
            name="compose_project",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name="application",
            name="container_name",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="application",
            name="workdir",
            field=models.CharField(blank=True, max_length=512),
        ),
        migrations.AddField(
            model_name="application",
            name="mounts",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="application",
            name="env_location",
            field=models.CharField(
                choices=[("host", "On the server"), ("container", "Inside the container")],
                default="host",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="application",
            name="deploy_steps",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="application",
            name="discovered_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
