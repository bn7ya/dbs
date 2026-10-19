from django.apps import AppConfig


class DbsConfig(AppConfig):
    name = "dbs"
    verbose_name = "Django Backup Solution"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from django.utils.module_loading import autodiscover_modules

        from django.core.signals import request_started

        from .schedule_runner import ensure_started

        autodiscover_modules("dbs")
        from .security import checks, signals  # noqa: F401

        request_started.connect(ensure_started, dispatch_uid="dbs.schedule_runner")

