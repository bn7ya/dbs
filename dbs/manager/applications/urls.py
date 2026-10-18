from django.urls import path

from dbs.manager.applications.views import (
    ApplicationDetailView,
    ApplicationListView,
    CheckView,
    DiscoverView,
    PassphraseCaptureView,
    PassphraseView,
)

app_name = "applications"

urlpatterns = [
    path("", ApplicationListView.as_view(), name="list"),
    path("discover/", DiscoverView.as_view(), name="discover"),
    path("<uuid:pk>/", ApplicationDetailView.as_view(), name="detail"),
    path("<uuid:pk>/check/", CheckView.as_view(), name="check"),
    path("<uuid:pk>/passphrase/", PassphraseView.as_view(), name="passphrase"),
    path(
        "<uuid:pk>/passphrase/capture/",
        PassphraseCaptureView.as_view(),
        name="passphrase-capture",
    ),
]
