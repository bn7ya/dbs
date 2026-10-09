from django.urls import include, path, re_path

from dbs.manager import spa
from dbs.manager.accounts.views import SetupView
from dbs.manager.common.views import HealthView
from dbs.manager.dashboard.views import AboutView, DashboardView
from dbs.manager.redeploy.views import RedeployView

api_patterns = [
    path("health/", HealthView.as_view(), name="health"),
    path("setup/", SetupView.as_view(), name="setup"),
    path("auth/", include("dbs.manager.accounts.urls")),
    path("activity/", include("dbs.manager.activity.urls")),
    path("servers/", include("dbs.manager.servers.urls")),
    path("backups/", include("dbs.manager.backups.urls")),
    path("files/", include("dbs.manager.files.urls")),
    path("envfiles/", include("dbs.manager.envfiles.urls")),
    path("dashboard/", DashboardView.as_view(), name="dashboard"),
    path("about/", AboutView.as_view(), name="about"),
    path("redeploy/", RedeployView.as_view(), name="redeploy"),
]

urlpatterns = [
    path("api/", include(api_patterns)),
    re_path(r"^api(?:/(?P<path>.*))?$", spa.api_not_found),
    path("static/dbs_manager/<path:path>", spa.asset, name="asset"),
    re_path(r"^(?P<path>.*)$", spa.index, name="index"),
]
