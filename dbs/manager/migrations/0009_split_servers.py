from django.db import migrations

SSH_FIELDS = (
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
)


def split(apps, schema_editor):
    Application = apps.get_model("dbs_manager", "Application")
    Server = apps.get_model("dbs_manager", "Server")
    for application in Application._base_manager.order_by("created_at"):
        server = Server._base_manager.create(
            name=application.name,
            created_by_id=application.created_by_id,
            deleted_at=application.deleted_at,
            **{name: getattr(application, name) for name in SSH_FIELDS},
        )
        Server._base_manager.filter(pk=server.pk).update(created_at=application.created_at)
        application.server = server
        if application.runtime == "compose":
            application.kind = "compose"
            application.engine = "docker"
        application.save(update_fields=["server", "kind", "engine"])


def join(apps, schema_editor):
    Application = apps.get_model("dbs_manager", "Application")
    Server = apps.get_model("dbs_manager", "Server")
    for application in Application._base_manager.exclude(server=None):
        server = Server._base_manager.get(pk=application.server_id)
        for name in SSH_FIELDS:
            setattr(application, name, getattr(server, name))
        application.runtime = "compose" if application.kind != "host" else "host"
        application.server = None
        application.save()
    Server._base_manager.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("dbs_manager", "0008_application"),
    ]

    operations = [
        migrations.RunPython(split, join),
    ]
