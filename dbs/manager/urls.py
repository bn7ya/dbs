from django.urls import include, path, re_path

from dbs.manager import spa
from dbs.manager.accounts.views import SetupView
from dbs.manager.common.views import HealthView

api_patterns = [
    path("health/", HealthView.as_view(), name="health"),
    path("setup/", SetupView.as_view(), name="setup"),
    path("auth/", include("dbs.manager.accounts.urls")),
    path("activity/", include("dbs.manager.activity.urls")),
    path("servers/", include("dbs.manager.servers.urls")),
]

urlpatterns = [
    path("api/", include(api_patterns)),
    re_path(r"^api(?:/(?P<path>.*))?$", spa.api_not_found),
    path("static/dbs_manager/<path:path>", spa.asset, name="asset"),
    re_path(r"^(?P<path>.*)$", spa.index, name="index"),
]
