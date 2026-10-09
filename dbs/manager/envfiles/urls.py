from django.urls import path

from dbs.manager.envfiles.views import (
    EnvCompareView,
    EnvPullView,
    EnvPushView,
    EnvRevealView,
    EnvVersionDetailView,
    EnvVersionListView,
)

app_name = "envfiles"

urlpatterns = [
    path("", EnvVersionListView.as_view(), name="list"),
    path("pull/", EnvPullView.as_view(), name="pull"),
    path("<uuid:pk>/", EnvVersionDetailView.as_view(), name="detail"),
    path("<uuid:pk>/compare/", EnvCompareView.as_view(), name="compare"),
    path("<uuid:pk>/reveal/", EnvRevealView.as_view(), name="reveal"),
    path("<uuid:pk>/push/", EnvPushView.as_view(), name="push"),
]
