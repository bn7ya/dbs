from django.apps import AppConfig


class DbsConfig(AppConfig):
    name = "dbs"
    verbose_name = "Django Backup Solution"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from django.utils.module_loading import autodiscover_modules

        from django.core.signals import request_started
        from django.db.models.signals import post_migrate, pre_migrate

        from .schedule_runner import ensure_started

        autodiscover_modules("dbs")
        from .security import checks, signals  # noqa: F401

        request_started.connect(ensure_started, dispatch_uid="dbs.schedule_runner")
        pre_migrate.connect(before_migrate, sender=self, dispatch_uid="dbs.checkpoint.before")
        post_migrate.connect(after_migrate, sender=self, dispatch_uid="dbs.checkpoint.after")


def before_migrate(sender, **kwargs):
    from . import checkpoints

    checkpoints.before_migrate(sender, **kwargs)


def after_migrate(sender, **kwargs):
    from . import checkpoints

    checkpoints.after_migrate(sender, **kwargs)

