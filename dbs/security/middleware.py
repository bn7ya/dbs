from __future__ import annotations

from django.contrib.auth import logout
from django.contrib.auth.views import redirect_to_login
from django.http import JsonResponse
from django.shortcuts import redirect
from django.conf import settings
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from ..conf import setting
from ..models import SecurityPolicy
from . import guard

SESSION_STARTED = "dbs_session_started"

ADMIN_ACTIONS = (
    ("/restore/", "restore"),
    ("/console/", "console"),
    ("/download/", "download"),
    ("/create/", "backup"),
    ("/delete/", "delete"),
    ("/backuptarget/", "target_write"),
)


class DBSSecurityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated or not user.is_superuser:
            return self.get_response(request)
        scope = self._scope(request)
        if scope is None:
            return self.get_response(request)

        request.session.setdefault(SESSION_STARTED, timezone.now().isoformat())

        if guard.is_locked_out(user):
            return self._stop(request, "Your session was ended by the DBS guard.")

        if scope == "admin":
            redirect_response = self._setup_redirect(request)
            if redirect_response is not None:
                return redirect_response

        verdict = guard.evaluate(request, action=self._action(request.path))
        guard.apply(verdict, request)
        if verdict.level == guard.BLOCK:
            return self._stop(request, "; ".join(verdict.reasons))
        request.dbs_verdict = verdict
        return self.get_response(request)

    def _scope(self, request):
        path = request.path
        if path.startswith(settings.STATIC_URL or "/static/"):
            return None
        try:
            admin_root = reverse("admin:index")
        except NoReverseMatch:
            admin_root = "/admin/"
        if path.startswith(admin_root):
            if path.startswith(admin_root + "logout"):
                return None
            return "admin"
        if _contrib_paths() and path in _contrib_paths():
            return "contrib"
        return None

    def _action(self, path) -> str:
        for fragment, name in ADMIN_ACTIONS:
            if fragment in path:
                return name
        return "view"

    def _setup_redirect(self, request):
        if not setting("DBS_SETUP_WIZARD", True):
            return None
        try:
            wizard = reverse("admin:dbs_setup")
        except NoReverseMatch:
            return None
        if request.path in (wizard, reverse("admin:dbs_guard")):
            return None
        if SecurityPolicy.load().configured:
            return None
        return redirect(wizard)

    def _stop(self, request, message):
        logout(request)
        if request.headers.get("x-requested-with") == "XMLHttpRequest" or request.path.endswith(
            "/guard/"
        ):
            return JsonResponse(
                {"authorized": False, "action": "logout", "reasons": [message]},
                status=401,
            )
        return redirect_to_login(request.get_full_path())


def _contrib_paths():
    paths = []
    for name in ("dbs:backup_download", "dbs:restore_upload"):
        try:
            paths.append(reverse(name))
        except NoReverseMatch:
            continue
    return paths
