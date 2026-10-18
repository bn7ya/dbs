import django.db.models.deletion
from django.db import migrations, models

MOVED = (
    "host",
    "port",
    "username",
    "auth_method",
    "private_key_sealed",
    "key_passphrase_sealed",
    "password_sealed",
    "host_key",
    "host_key_fingerprint",
    "timeout_on_host",
    "connection_state",
    "last_seen_at",
    "last_connection_error",
    "runtime",
)
REFILLED_ON_REVERSE = {
    "host": models.CharField(default="", max_length=255),
    "username": models.CharField(default="", max_length=64),
    "auth_method": models.CharField(
        choices=[("key", "Private key"), ("password", "Password")],
        default="key",
        max_length=16,
    ),
    "host_key": models.TextField(default=""),
    "host_key_fingerprint": models.CharField(default="", max_length=100),
}


class Migration(migrations.Migration):
    dependencies = [
        ("dbs_manager", "0009_split_servers"),
    ]

    operations = [
        *[
            migrations.AlterField(model_name="application", name=name, field=field)
            for name, field in REFILLED_ON_REVERSE.items()
        ],
        *[
            migrations.RemoveField(model_name="application", name=name)
            for name in MOVED
        ],
        migrations.AlterField(
            model_name="application",
            name="server",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="applications",
                to="dbs_manager.server",
            ),
        ),
        migrations.AddConstraint(
            model_name="application",
            constraint=models.UniqueConstraint(
                condition=models.Q(("deleted_at__isnull", True)),
                fields=("name",),
                name="dbs_manager_application_unique_active_name",
            ),
        ),
        migrations.AddConstraint(
            model_name="server",
            constraint=models.UniqueConstraint(
                condition=models.Q(("deleted_at__isnull", True)),
                fields=("name",),
                name="dbs_manager_server_unique_active_name",
            ),
        ),
    ]
