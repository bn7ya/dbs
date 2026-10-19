from django.urls import path

from dbs.manager.files.views import (
    DownloadView,
    FolderCreateView,
    FolderView,
    UploadView,
)

app_name = "files"

urlpatterns = [
    path("<uuid:application>/", FolderView.as_view(), name="folder"),
    path("<uuid:application>/download/", DownloadView.as_view(), name="download"),
    path("<uuid:application>/upload/", UploadView.as_view(), name="upload"),
    path("<uuid:application>/folders/", FolderCreateView.as_view(), name="folders"),
]
