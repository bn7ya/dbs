from django.urls import path

from dbs.manager.files.views import (
    DownloadView,
    FolderCreateView,
    FolderView,
    UploadView,
)

app_name = "files"

urlpatterns = [
    path("<uuid:server>/", FolderView.as_view(), name="folder"),
    path("<uuid:server>/download/", DownloadView.as_view(), name="download"),
    path("<uuid:server>/upload/", UploadView.as_view(), name="upload"),
    path("<uuid:server>/folders/", FolderCreateView.as_view(), name="folders"),
]
