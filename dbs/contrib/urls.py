"""URL patterns for the optional DBS admin views."""

from django.urls import path

from .admin import backup_download, restore_upload

app_name = "dbs"

urlpatterns = [
    path("backup/", backup_download, name="backup_download"),
    path("restore/", restore_upload, name="restore_upload"),
]
