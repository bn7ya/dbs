"""Django app configuration for DBS."""

from django.apps import AppConfig


class DbsConfig(AppConfig):
    name = "dbs"
    verbose_name = "Django Backup Solution"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        # Auto-discover ``dbs.py`` modules in installed apps, mirroring how the
        # admin discovers ``admin.py``. This lets projects register models via
        # ``@backup_registry.register(...)`` without an explicit import.
        from django.utils.module_loading import autodiscover_modules

        autodiscover_modules("dbs")
