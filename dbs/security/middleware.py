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
from . import guard, sessions, telemetry

SESSION_STARTED = "dbs_session_started"

UNSAFE_METHODS = ("POST", "PUT", "PATCH", "DELETE")

ADMIN_ACTIONS = (
    ("/restore/", "restore"),
    ("/download/", "download"),
    ("/create/", "backup"),
    ("/delete/", "delete"),
    ("/panel/setup/", "settings_write"),
    ("/securitypolicy/", "settings_write"),
    ("/knownlocation/", "settings_write"),
    ("/backupschedule/", "settings_write"),
)

EXPORT_FRAGMENTS = ("/download/", "/export/")

CONTRIB_ACTIONS = (
    ("dbs:backup_download", "download"),
    ("dbs:restore_upload", "restore"),
)

FLAGGED = "DBS flagged this session, so it must sign in again before doing this."

IDLE = "This session was idle for too long, so DBS ended it."


class DBSSecurityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated or not user.is_superuser:
            return self.get_response(request)

        if guard.is_locked_out(user):
            return self._stop(request, "Your session was ended by the DBS guard.")

        scope = self._scope(request)
        if scope is None:
            return self.get_response(request)

        policy = SecurityPolicy.load()
        now = timezone.now().timestamp()
        if sessions.idle_expired(request, policy.idle_timeout_minutes, now):
            return self._stop(request, IDLE)

        request.session.setdefault(SESSION_STARTED, timezone.now().isoformat())
        guard_endpoint = self._is_guard_endpoint(request)
        if not guard_endpoint:
            sessions.mark_active(request, now)

        if scope == "admin":
            redirect_response = self._setup_redirect(request, policy)
            if redirect_response is not None:
                return redirect_response

        action = self._action(request, scope)
        restricted = not guard_endpoint and self._restricted(request, action)
        if restricted and sessions.must_reauthenticate(request):
            return self._stop(request, FLAGGED)

        if guard_endpoint:
            return self.get_response(request)

        telemetry.purge_if_due()
        verdict = guard.evaluate(request, action=action, policy=policy)
        guard.apply(verdict, request)
        if verdict.level == guard.BLOCK:
            return self._stop(request, "; ".join(verdict.reasons))
        if restricted and sessions.must_reauthenticate(request):
            return self._stop(request, FLAGGED)
        request.dbs_verdict = verdict
        return self._with_poller(request, self.get_response(request), scope)

    def _with_poller(self, request, response, scope):
        if scope != "admin" or not setting("DBS_GUARD_EVERYWHERE", False):
            return response
        if getattr(response, "streaming", False) or response.status_code != 200:
            return response
        if "text/html" not in response.get("Content-Type", ""):
            return response
        body = response.content.decode(response.charset or "utf-8", "replace")
        if "id=\"dbs-guard\"" in body or "</body>" not in body:
            return response
        response.content = body.replace("</body>", _poller_tag() + "</body>", 1).encode(
            response.charset or "utf-8"
        )
        if response.has_header("Content-Length"):
            response["Content-Length"] = str(len(response.content))
        return response

    def _is_guard_endpoint(self, request) -> bool:
        try:
            return request.path == reverse("admin:dbs_guard")
        except NoReverseMatch:
            return False

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

    def _action(self, request, scope) -> str:
        unsafe = request.method in UNSAFE_METHODS
        if scope == "contrib":
            return _contrib_action(request.path) if unsafe else "view"
        if any(fragment in request.path for fragment in EXPORT_FRAGMENTS):
            return "download"
        if not unsafe:
            return "view"
        if _is_account_path(request.path):
            return "account_write"
        for fragment, name in ADMIN_ACTIONS:
            if fragment in request.path:
                return name
        return "view"

    def _restricted(self, request, action) -> bool:
        return request.method in UNSAFE_METHODS or action == "download"

    def _setup_redirect(self, request, policy):
        if not setting("DBS_SETUP_WIZARD", True) or not request.user.is_staff:
            return None
        try:
            wizard = reverse("admin:dbs_setup")
        except NoReverseMatch:
            return None
        if request.path in (wizard, reverse("admin:dbs_guard")):
            return None
        if policy.configured:
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
    for name, _ in CONTRIB_ACTIONS:
        try:
            paths.append(reverse(name))
        except NoReverseMatch:
            continue
    return paths


def _contrib_action(path) -> str:
    for name, action in CONTRIB_ACTIONS:
        try:
            if path == reverse(name):
                return action
        except NoReverseMatch:
            continue
    return "download"


def _account_paths():
    from django.contrib.auth import get_user_model
    from django.contrib.auth.models import Group, Permission

    names = ["admin:password_change"]
    for model in (get_user_model(), Group, Permission):
        names.append(f"admin:{model._meta.app_label}_{model._meta.model_name}_changelist")
    paths = []
    for name in names:
        try:
            paths.append(reverse(name))
        except NoReverseMatch:
            continue
    return paths


def _is_account_path(path) -> bool:
    return any(path.startswith(prefix) for prefix in _account_paths())


def _poller_tag() -> str:
    from django.templatetags.static import static

    return (
        f'<script id="dbs-guard" src="{static("dbs/guard.js")}" '
        f'data-url="{reverse("admin:dbs_guard")}" '
        f'data-login="{reverse("admin:login")}"></script>'
    )
