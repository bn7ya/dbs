from django.apps import AppConfig


class DbsConfig(AppConfig):
    name = "dbs"
    verbose_name = "Django Backup Solution"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from django.utils.module_loading import autodiscover_modules

        autodiscover_modules("dbs")
