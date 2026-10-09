from django.urls import path

from dbs.manager.servers.views import (
    CheckView,
    FingerprintView,
    HostKeyView,
    PassphraseView,
    ServerDetailView,
    ServerListView,
)

app_name = "servers"

urlpatterns = [
    path("", ServerListView.as_view(), name="list"),
    path("fingerprint/", FingerprintView.as_view(), name="fingerprint"),
    path("<uuid:pk>/", ServerDetailView.as_view(), name="detail"),
    path("<uuid:pk>/check/", CheckView.as_view(), name="check"),
    path("<uuid:pk>/host-key/", HostKeyView.as_view(), name="host-key"),
    path("<uuid:pk>/passphrase/", PassphraseView.as_view(), name="passphrase"),
]
