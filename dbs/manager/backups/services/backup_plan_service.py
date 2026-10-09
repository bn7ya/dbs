from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import QuerySet
from django.utils import timezone
from rest_framework.exceptions import ErrorDetail, NotFound, ValidationError

from dbs.manager.accounts.services import AccountService
from dbs.manager.activity.services import ActivityService
from dbs.manager.backups.models import PLAN_PATTERN_MAX_LENGTH, BackupPlan
from dbs.manager.backups.repositories import BackupPlanRepository
from dbs.manager.backups.services.actions import Action
from dbs.manager.backups.services.backup_run_service import BackupRunService
from dbs.manager.backups.services.job_queue import JobQueue
from dbs.manager.backups.services.plan_runs import run_detail
from dbs.manager.common.paths import absolute_path
from dbs.manager.runner import get_runner
from dbs.manager.servers.services import ServerService
from dbs.models import AuditEvent

if TYPE_CHECKING:
    from django.contrib.auth.models import AnonymousUser, User

INTERVALS = (60, 180, 360, 720, 1440, 10080)
EDITABLE_FIELDS = (
    "name",
    "paths",
    "pattern",
    "interval_minutes",
    "keep",
    "keep_remote",
    "enabled",
)
SCHEDULE_FIELDS = ("interval_minutes", "enabled")
READ_FIELDS = ("paths", "pattern")
ENABLED_BY_DEFAULT = BackupPlan._meta.get_field("enabled").get_default()
DEFAULT_PATTERN = "*"

NAME_TAKEN = "Another plan for this server already has this name."
INVALID_INTERVAL = "Choose hourly, every 3, 6 or 12 hours, daily, weekly, or none."
PATHS_REQUIRED = "Add at least one folder or file to archive."
ABSOLUTE_PATH_REQUIRED = (
    "Use an absolute path that starts with / and has no '..' in it."
)
PATHS_NOT_ALLOWED = "Only a plan that archives or collects from folders takes paths."
ONE_FOLDER_REQUIRED = "Choose one folder to collect files from."
INVALID_PATTERN = "Use a file name pattern of 1 to 200 characters with no '/' in it, such as *.sql.gz."
ACCOUNT_PASSWORD_REQUIRED = (
    "Enter your own password to choose what is read from the server."
)

Errors = dict[str, list[ErrorDetail]]


def first_run(interval_minutes: int | None, enabled: bool) -> datetime | None:
    if interval_minutes is None or not enabled:
        return None
    return timezone.now() + timedelta(minutes=interval_minutes)


def _add(errors: Errors, field: str, message: str, code: str) -> None:
    errors.setdefault(field, []).append(ErrorDetail(message, code=code))


def _require_password(account_password: str, guarded: bool) -> None:
    if guarded and not account_password:
        raise ValidationError(
            {
                "account_password": [
                    ErrorDetail(ACCOUNT_PASSWORD_REQUIRED, code="required")
                ]
            }
        )


def _is_pattern(pattern: str) -> bool:
    return (
        0 < len(pattern) <= PLAN_PATTERN_MAX_LENGTH
        and "/" not in pattern
        and "\x00" not in pattern
    )


class BackupPlanService:
    def __init__(self, user: User | AnonymousUser | None) -> None:
        self.user: User | AnonymousUser | None = user
        self.plans = BackupPlanRepository()
        self.servers = ServerService(user)
        self.activity = ActivityService(user)
        self.jobs = JobQueue(user)

    def list(self, server_id: UUID) -> QuerySet[BackupPlan]:
        return self.plans.alive_for_server(server_id)

    def get(self, plan_id: UUID) -> BackupPlan:
        plan = self.plans.find(plan_id)
        if plan is None:
            raise NotFound()
        return plan

    def create(
        self, *, server: UUID, account_password: str = "", **data: Any
    ) -> BackupPlan:
        target = self.servers.get(server)
        data = self._validated(target.pk, data["kind"], data, plan=None)
        fields = {
            name: data[name] for name in ("kind", *EDITABLE_FIELDS) if name in data
        }
        fields["next_run_at"] = first_run(
            fields.get("interval_minutes"), fields.get("enabled", ENABLED_BY_DEFAULT)
        )
        guarded = fields["kind"] != BackupPlan.Kind.DBS
        _require_password(account_password, guarded)
        with self.activity.track(
            Action.PLAN_CREATE, server=target, target=fields["name"]
        ):
            if guarded:
                AccountService(self.user).confirm_password(account_password)
            return self._saved(
                lambda: self.plans.create(
                    created_by=cast("User | None", self.user), server=target, **fields
                )
            )

    def update(
        self, plan_id: UUID, account_password: str = "", **data: Any
    ) -> BackupPlan:
        plan = self.get(plan_id)
        data = self._validated(plan.server_id, plan.kind, data, plan=plan)
        changes = {
            name: data[name]
            for name in EDITABLE_FIELDS
            if name in data and getattr(plan, name) != data[name]
        }
        if any(name in changes for name in SCHEDULE_FIELDS):
            changes["next_run_at"] = first_run(
                changes.get("interval_minutes", plan.interval_minutes),
                changes.get("enabled", plan.enabled),
            )
        changed = sorted(name for name in changes if name in EDITABLE_FIELDS)
        guarded = any(name in changes for name in READ_FIELDS)
        _require_password(account_password, guarded)
        name = changes.get("name", plan.name)
        with self.activity.track(
            Action.PLAN_UPDATE, server=plan.server, target=name
        ) as entry:
            entry.detail = {"fields": changed}
            if guarded:
                AccountService(self.user).confirm_password(account_password)
            return self._saved(lambda: self.plans.update(plan, **changes))

    def delete(self, plan_id: UUID) -> None:
        plan = self.get(plan_id)
        with transaction.atomic():
            self.plans.soft_delete(plan)
            self.activity.record(
                Action.PLAN_DELETE, server=plan.server, target=plan.name
            )

    def run(self, plan_id: UUID) -> AuditEvent:
        plan = self.get(plan_id)
        server = self.servers.get(plan.server_id)
        return self.jobs.queue_backup(
            Action.RUN,
            server=server,
            target=plan.name,
            detail=run_detail(plan),
            send=lambda job: get_runner().submit(
                BackupRunService().run_plan, job.pk, plan.pk
            ),
        )

    def _validated(
        self,
        server_id: UUID,
        kind: str,
        data: dict[str, Any],
        *,
        plan: BackupPlan | None,
    ) -> dict[str, Any]:
        errors: Errors = {}
        excluding = None if plan is None else plan.pk
        if "name" in data and self.plans.name_in_use(
            server_id, data["name"], excluding=excluding
        ):
            _add(errors, "name", NAME_TAKEN, "name_taken")
        interval = data.get("interval_minutes")
        if interval is not None and interval not in INTERVALS:
            _add(errors, "interval_minutes", INVALID_INTERVAL, "invalid_interval")
        validated = dict(data)
        if kind == BackupPlan.Kind.DBS:
            if data.get("paths"):
                _add(errors, "paths", PATHS_NOT_ALLOWED, "paths_not_allowed")
            validated.pop("paths", None)
        elif plan is None or "paths" in data:
            paths = list(
                dict.fromkeys(absolute_path(path) for path in data.get("paths", []))
            )
            if not paths:
                _add(errors, "paths", PATHS_REQUIRED, "paths_required")
            elif None in paths:
                _add(errors, "paths", ABSOLUTE_PATH_REQUIRED, "absolute_path_required")
            elif kind == BackupPlan.Kind.COLLECT and len(paths) > 1:
                _add(errors, "paths", ONE_FOLDER_REQUIRED, "one_folder_required")
            validated["paths"] = paths
        if kind == BackupPlan.Kind.COLLECT:
            if plan is None:
                validated.setdefault("pattern", DEFAULT_PATTERN)
                validated["keep_remote"] = 0
            else:
                validated.pop("keep_remote", None)
            if "pattern" in validated and not _is_pattern(validated["pattern"]):
                _add(errors, "pattern", INVALID_PATTERN, "invalid_pattern")
        else:
            validated.pop("pattern", None)
        if errors:
            raise ValidationError(errors)
        return validated

    def _saved(self, write: Callable[[], BackupPlan]) -> BackupPlan:
        try:
            with transaction.atomic():
                return write()
        except IntegrityError as exc:
            raise ValidationError(
                {"name": [ErrorDetail(NAME_TAKEN, code="name_taken")]}
            ) from exc
