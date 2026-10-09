from django.urls import path

from dbs.manager.backups.views import (
    BackupDetailView,
    BackupListView,
    DownloadView,
    PlanDetailView,
    PlanListView,
    PlanRunView,
    RestoreView,
    TakeView,
    UndoDeleteView,
    UploadView,
    VerifyView,
)

app_name = "backups"

urlpatterns = [
    path("", BackupListView.as_view(), name="list"),
    path("take/", TakeView.as_view(), name="take"),
    path("upload/", UploadView.as_view(), name="upload"),
    path("plans/", PlanListView.as_view(), name="plan-list"),
    path("plans/<uuid:pk>/", PlanDetailView.as_view(), name="plan-detail"),
    path("plans/<uuid:pk>/run/", PlanRunView.as_view(), name="plan-run"),
    path("<uuid:pk>/", BackupDetailView.as_view(), name="detail"),
    path("<uuid:pk>/download/", DownloadView.as_view(), name="download"),
    path("<uuid:pk>/verify/", VerifyView.as_view(), name="verify"),
    path("<uuid:pk>/restore/", RestoreView.as_view(), name="restore"),
    path("<uuid:pk>/undo-delete/", UndoDeleteView.as_view(), name="undo-delete"),
]
