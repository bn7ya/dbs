from django.urls import path

from dbs.manager.shell.views import (
    TerminalDetailView,
    TerminalInputView,
    TerminalListView,
    TerminalOutputView,
    TerminalResizeView,
)

app_name = "terminals"

urlpatterns = [
    path("", TerminalListView.as_view(), name="list"),
    path("<str:identifier>/", TerminalDetailView.as_view(), name="detail"),
    path("<str:identifier>/output/", TerminalOutputView.as_view(), name="output"),
    path("<str:identifier>/input/", TerminalInputView.as_view(), name="input"),
    path("<str:identifier>/resize/", TerminalResizeView.as_view(), name="resize"),
]
