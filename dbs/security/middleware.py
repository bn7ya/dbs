from __future__ import annotations

import logging
from dataclasses import dataclass

from django.contrib.auth import logout
from django.contrib.auth.views import redirect_to_login
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.conf import settings
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from ..conf import setting
from ..models import SecurityPolicy
from . import guard, sessions, telemetry

logger = logging.getLogger("dbs")

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

FLAGGED = "DBS flagged this session, so it must sign in again before doing this."

IDLE = "This session was idle for too long, so DBS ended it."

LOCKED_OUT = "Your session was ended by the DBS guard."

UNDECIDED = (
    "DBS could not check this session, so the admin refuses changes and downloads until it "
    "can. The reason is in the dbs log."
)

UNENDED = (
    "DBS decided to end this session but could not; this request is refused. The reason is "
    "in the dbs log."
)

RETRY_SECONDS = 60


@dataclass
class Inspection:
    scope: str | None = None
    restricted: bool = False
    ending: bool = False
    poller: bool = False


class DBSSecurityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated or not user.is_superuser:
            return self.get_response(request)

        inspection = Inspection()
        try:
            stopped = self._inspect(request, inspection)
        except Exception:
            logger.exception(
                "the DBS session guard could not check %s %s", request.method, request.path
            )
            stopped = self._undecided(request, inspection)
        if stopped is not None:
            return stopped

        response = self.get_response(request)
        if not inspection.poller:
            return response
        try:
            return self._with_poller(response)
        except Exception:
            logger.exception("the DBS guard poller could not be added to %s", request.path)
            return response

    def _inspect(self, request, inspection):
        inspection.scope = self._scope(request)
        inspection.restricted = self._restricted(request)

        if guard.is_locked_out(request.user):
            inspection.ending = True
            return self._stop(request, LOCKED_OUT)

        if inspection.scope is None:
            return None

        policy = SecurityPolicy.load()
        now = timezone.now().timestamp()
        if sessions.idle_expired(request, policy.idle_timeout_minutes, now):
            inspection.ending = True
            return self._stop(request, IDLE)

        request.session.setdefault(SESSION_STARTED, timezone.now().isoformat())
        guard_endpoint = self._is_guard_endpoint(request)
        if not guard_endpoint:
            sessions.mark_active(request, now)

        redirect_response = self._setup_redirect(request, policy)
        if redirect_response is not None:
            return redirect_response

        action = self._action(request, inspection.scope)
        restricted = not guard_endpoint and inspection.restricted
        if restricted and sessions.must_reauthenticate(request):
            inspection.ending = True
            return self._stop(request, FLAGGED)

        if guard_endpoint:
            return None

        telemetry.purge_if_due()
        verdict = guard.evaluate(request, action=action, policy=policy)
        inspection.ending = verdict.level == guard.BLOCK
        guard.apply(verdict, request)
        if verdict.level == guard.BLOCK:
            return self._stop(request, "; ".join(verdict.reasons))
        if restricted and sessions.must_reauthenticate(request):
            inspection.ending = True
            return self._stop(request, FLAGGED)
        request.dbs_verdict = verdict
        inspection.poller = bool(setting("DBS_GUARD_EVERYWHERE", False))
        return None

    def _undecided(self, request, inspection):
        if inspection.ending or (inspection.scope is not None and inspection.restricted):
            return refusal(request, ending=inspection.ending)
        return None

    def _with_poller(self, response):
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
        return None

    def _action(self, request, scope) -> str:
        unsafe = request.method in UNSAFE_METHODS
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

    def _restricted(self, request) -> bool:
        return request.method in UNSAFE_METHODS or any(
            fragment in request.path for fragment in EXPORT_FRAGMENTS
        )

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
        if wants_json(request):
            return JsonResponse(
                {"authorized": False, "action": "logout", "reasons": [message]},
                status=401,
            )
        return redirect_to_login(request.get_full_path())


def wants_json(request) -> bool:
    return request.headers.get("x-requested-with") == "XMLHttpRequest" or (
        request.path.endswith("/guard/")
    )


def refusal(request, *, ending):
    message, status = (UNENDED, 403) if ending else (UNDECIDED, 503)
    if wants_json(request):
        return JsonResponse(
            {
                "authorized": False,
                "action": "logout" if ending else "refused",
                "reasons": [message],
                "poll_after": RETRY_SECONDS,
            },
            status=status,
        )
    return HttpResponse(message, status=status, content_type="text/plain; charset=utf-8")


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
