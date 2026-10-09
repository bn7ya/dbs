from django.apps import AppConfig
from django.db.backends.signals import connection_created

SQLITE_PRAGMAS = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA busy_timeout=30000",
    "PRAGMA foreign_keys=ON",
)


def tune_sqlite(sender, connection, **kwargs):
    if connection.vendor != "sqlite":
        return
    with connection.cursor() as cursor:
        for pragma in SQLITE_PRAGMAS:
            cursor.execute(pragma)


class ManagerConfig(AppConfig):
    name = "dbs.manager"
    label = "dbs_manager"
    verbose_name = "DBS manager"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        connection_created.connect(tune_sqlite, dispatch_uid="dbs.manager.sqlite")
