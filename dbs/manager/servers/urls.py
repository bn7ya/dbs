from django.urls import path

from dbs.manager.servers.views import (
    BrowseView,
    CheckView,
    FingerprintView,
    HostKeyConfirmationListView,
    HostKeyConfirmView,
    HostKeyRejectView,
    HostKeyView,
    MergeView,
    PublicKeyView,
    ServerDetailView,
    ServerListView,
)

app_name = "servers"

urlpatterns = [
    path("", ServerListView.as_view(), name="list"),
    path("fingerprint/", FingerprintView.as_view(), name="fingerprint"),
    path(
        "host-keys/",
        HostKeyConfirmationListView.as_view(),
        name="host-key-confirmations",
    ),
    path(
        "host-keys/<str:confirmation>/confirm/",
        HostKeyConfirmView.as_view(),
        name="host-key-confirm",
    ),
    path(
        "host-keys/<str:confirmation>/reject/",
        HostKeyRejectView.as_view(),
        name="host-key-reject",
    ),
    path("<uuid:pk>/", ServerDetailView.as_view(), name="detail"),
    path("<uuid:pk>/check/", CheckView.as_view(), name="check"),
    path("<uuid:pk>/host-key/", HostKeyView.as_view(), name="host-key"),
    path("<uuid:pk>/public-key/", PublicKeyView.as_view(), name="public-key"),
    path("<uuid:pk>/browse/", BrowseView.as_view(), name="browse"),
    path("<uuid:pk>/merge/", MergeView.as_view(), name="merge"),
]
