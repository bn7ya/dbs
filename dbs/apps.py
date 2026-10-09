from django.apps import AppConfig

HYPHEN_ALIASES = ("django-dbs", "dbs-upgrade")


class DbsConfig(AppConfig):
    name = "dbs"
    verbose_name = "Django Backup Solution"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from django.utils.module_loading import autodiscover_modules

        from django.core.signals import request_started

        from .schedule_runner import ensure_started

        autodiscover_modules("dbs")
        install_hyphen_aliases()
        from .security import signals  # noqa: F401

        request_started.connect(ensure_started, dispatch_uid="dbs.schedule_runner")


def install_hyphen_aliases():
    from django.core import management

    if getattr(management, "_dbs_hyphen_aliases", False):
        return

    original_get_commands = management.get_commands
    original_load = management.load_command_class

    def get_commands():
        commands = original_get_commands()
        for alias in HYPHEN_ALIASES:
            module = alias.replace("-", "_")
            if module in commands:
                commands.setdefault(alias, commands[module])
        return commands

    def load_command_class(app_name, name):
        if name in HYPHEN_ALIASES:
            name = name.replace("-", "_")
        return original_load(app_name, name)

    get_commands.cache_clear = getattr(
        original_get_commands, "cache_clear", lambda: None
    )
    management.get_commands = get_commands
    management.load_command_class = load_command_class
    management._dbs_hyphen_aliases = True
