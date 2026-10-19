from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import QuerySet
from django.utils.text import slugify
from rest_framework.exceptions import ErrorDetail, NotFound, ValidationError

from dbs.manager.accounts.services import AccountService
from dbs.manager.activity.services import ActivityService
from dbs.manager.applications.services import ApplicationService
from dbs.manager.backups.models import PLAN_PATTERN_MAX_LENGTH, BackupPlan
from dbs.manager.backups.repositories import BackupPlanRepository
from dbs.manager.backups.services.actions import Action
from dbs.manager.backups.services.backup_run_service import BackupRunService
from dbs.manager.backups.services.job_queue import JobQueue
from dbs.manager.backups.services.plan_runs import run_detail
from dbs.manager.backups.timing import planned, within_reach, zone
from dbs.manager.common.paths import absolute_path
from dbs.manager.runner import get_runner
from dbs.manager.permissions import Capability, requires
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
    "anchor_at",
    "time_zone",
)
SCHEDULE_FIELDS = ("interval_minutes", "enabled", "anchor_at", "time_zone")
READ_FIELDS = ("paths", "pattern")
RETENTION_FIELDS = ("keep", "keep_remote")
ENABLED_BY_DEFAULT = BackupPlan._meta.get_field("enabled").get_default()
DEFAULT_TIME_ZONE = BackupPlan._meta.get_field("time_zone").get_default()
DEFAULT_PATTERN = "*"

NAME_TAKEN = "Another plan for this application already has this name."
SIMILAR_NAME_TAKEN = (
    "Another plan for this application has a name that differs only in case or "
    "punctuation, so their backups would share file names on the server."
)
INVALID_INTERVAL = "Choose hourly, every 3, 6 or 12 hours, daily, weekly, or none."
PATHS_REQUIRED = "Add at least one folder or file to archive."
ABSOLUTE_PATH_REQUIRED = (
    "Use an absolute path that starts with / and has no '..' in it."
)
PATHS_NOT_ALLOWED = "Only a plan that archives or collects from folders takes paths."
ONE_FOLDER_REQUIRED = "Choose one folder to collect files from."
INVALID_TIME_ZONE = "Choose a time zone by its name, such as Europe/Berlin."
INVALID_MOMENT = "Choose a moment after now and within a year."
MANUAL_PLAN = "This plan runs only when asked; give it an interval first."
INVALID_PATTERN = "Use a file name pattern of 1 to 200 characters with no '/' in it, such as *.sql.gz."
ACCOUNT_PASSWORD_REQUIRED = (
    "Enter your own password to choose what is read from the server."
)
RETENTION_PASSWORD_REQUIRED = (
    "Enter your own password to keep fewer backups: the next run deletes the oldest."
)

Errors = dict[str, list[ErrorDetail]]


def _add(errors: Errors, field: str, message: str, code: str) -> None:
    errors.setdefault(field, []).append(ErrorDetail(message, code=code))


def _require_password(
    account_password: str, guarded: bool, message: str = ACCOUNT_PASSWORD_REQUIRED
) -> None:
    if guarded and not account_password:
        raise ValidationError(
            {"account_password": [ErrorDetail(message, code="required")]}
        )


def _keeps_fewer(plan: BackupPlan, changes: Mapping[str, Any]) -> bool:
    return any(
        changes.get(name) is not None and changes[name] < getattr(plan, name)
        for name in RETENTION_FIELDS
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
        self.applications = ApplicationService(user)
        self.activity = ActivityService(user)
        self.jobs = JobQueue(user)

    def list(self, application_id: UUID) -> QuerySet[BackupPlan]:
        return self.plans.alive_for_application(application_id)

    def get(self, plan_id: UUID) -> BackupPlan:
        plan = self.plans.find(plan_id)
        if plan is None:
            raise NotFound()
        return plan

    @requires(Capability.PLANS_MANAGE)
    def create(
        self, *, application: UUID, account_password: str = "", **data: Any
    ) -> BackupPlan:
        target = self.applications.get(application)
        data = self._validated(target.pk, data["kind"], data, plan=None)
        fields = {
            name: data[name] for name in ("kind", *EDITABLE_FIELDS) if name in data
        }
        fields |= planned(
            fields.get("interval_minutes"),
            fields.get("enabled", ENABLED_BY_DEFAULT),
            fields.get("time_zone", DEFAULT_TIME_ZONE),
            fields.get("anchor_at"),
        )
        guarded = fields["kind"] != BackupPlan.Kind.DBS
        _require_password(account_password, guarded)
        with self.activity.track(
            Action.PLAN_CREATE, subject=target, target=fields["name"]
        ):
            if guarded:
                AccountService(self.user).confirm_password(account_password)
            return self._saved(
                lambda: self.plans.create(
                    created_by=cast("User | None", self.user),
                    application=target,
                    **fields,
                )
            )

    @requires(Capability.PLANS_MANAGE)
    def update(
        self, plan_id: UUID, account_password: str = "", **data: Any
    ) -> BackupPlan:
        plan = self.get(plan_id)
        data = self._validated(plan.application_id, plan.kind, data, plan=plan)
        changes = {
            name: data[name]
            for name in EDITABLE_FIELDS
            if name in data and getattr(plan, name) != data[name]
        }
        if any(name in changes for name in SCHEDULE_FIELDS):
            kept = None if "interval_minutes" in changes else plan.anchor_at
            changes |= planned(
                changes.get("interval_minutes", plan.interval_minutes),
                changes.get("enabled", plan.enabled),
                changes.get("time_zone", plan.time_zone),
                changes.get("anchor_at", kept),
            )
        changed = sorted(name for name in changes if name in EDITABLE_FIELDS)
        reads_elsewhere = any(name in changes for name in READ_FIELDS)
        guarded = reads_elsewhere or _keeps_fewer(plan, changes)
        _require_password(
            account_password,
            guarded,
            ACCOUNT_PASSWORD_REQUIRED
            if reads_elsewhere
            else RETENTION_PASSWORD_REQUIRED,
        )
        name = changes.get("name", plan.name)
        with self.activity.track(
            Action.PLAN_UPDATE, subject=plan.application, target=name
        ) as entry:
            entry.detail = {"fields": changed}
            if guarded:
                AccountService(self.user).confirm_password(account_password)
            return self._saved(lambda: self.plans.update(plan, **changes))

    def keeps_fewer(self, plan_id: UUID, changes: Mapping[str, Any]) -> bool:
        return _keeps_fewer(self.get(plan_id), changes)

    @requires(Capability.PLANS_MANAGE)
    def delete(self, plan_id: UUID) -> None:
        plan = self.get(plan_id)
        with transaction.atomic():
            self.plans.soft_delete(plan)
            self.activity.record(
                Action.PLAN_DELETE, subject=plan.application, target=plan.name
            )

    @requires(Capability.PLANS_MANAGE)
    def reschedule(self, plan_id: UUID, next_run_at: datetime) -> BackupPlan:
        plan = self._scheduled(plan_id)
        if not within_reach(next_run_at):
            raise ValidationError(
                {"next_run_at": [ErrorDetail(INVALID_MOMENT, code="invalid_moment")]}
            )
        timing = planned(plan.interval_minutes, plan.enabled, plan.time_zone, next_run_at)
        with self.activity.track(
            Action.PLAN_RESCHEDULE, subject=plan.application, target=plan.name
        ) as entry:
            entry.detail = {"next_run_at": next_run_at.isoformat()}
            return self.plans.update(plan, **timing)

    @requires(Capability.PLANS_MANAGE)
    def pause(self, plan_id: UUID) -> BackupPlan:
        plan = self._scheduled(plan_id)
        with transaction.atomic():
            self.activity.record(
                Action.PLAN_PAUSE, subject=plan.application, target=plan.name
            )
            return self.plans.update(plan, enabled=False, next_run_at=None)

    @requires(Capability.PLANS_MANAGE)
    def resume(self, plan_id: UUID) -> BackupPlan:
        plan = self._scheduled(plan_id)
        timing = planned(plan.interval_minutes, True, plan.time_zone, plan.anchor_at)
        with transaction.atomic():
            self.activity.record(
                Action.PLAN_RESUME, subject=plan.application, target=plan.name
            )
            return self.plans.update(plan, enabled=True, **timing)

    @requires(Capability.PLANS_RUN)
    def run(self, plan_id: UUID) -> AuditEvent:
        plan = self.get(plan_id)
        application = self.applications.get(plan.application_id)
        return self.jobs.queue_backup(
            Action.RUN,
            application=application,
            target=plan.name,
            detail=run_detail(plan),
            send=lambda job: get_runner().submit(
                BackupRunService().run_plan, job.pk, plan.pk
            ),
        )

    def _scheduled(self, plan_id: UUID) -> BackupPlan:
        plan = self.get(plan_id)
        if plan.interval_minutes is None:
            raise ValidationError(
                {"interval_minutes": [ErrorDetail(MANUAL_PLAN, code="manual_plan")]}
            )
        return plan

    def _validated(
        self,
        application_id: UUID,
        kind: str,
        data: dict[str, Any],
        *,
        plan: BackupPlan | None,
    ) -> dict[str, Any]:
        errors: Errors = {}
        excluding = None if plan is None else plan.pk
        if "name" in data:
            self._check_name(application_id, data["name"], excluding, errors)
        interval = data.get("interval_minutes")
        if interval is not None and interval not in INTERVALS:
            _add(errors, "interval_minutes", INVALID_INTERVAL, "invalid_interval")
        if "time_zone" in data and zone(data["time_zone"]) is None:
            _add(errors, "time_zone", INVALID_TIME_ZONE, "invalid_time_zone")
        if data.get("anchor_at") is not None and not within_reach(data["anchor_at"]):
            _add(errors, "anchor_at", INVALID_MOMENT, "invalid_moment")
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

    def _check_name(
        self, application_id: UUID, name: str, excluding: UUID | None, errors: Errors
    ) -> None:
        if self.plans.name_in_use(application_id, name, excluding=excluding):
            _add(errors, "name", NAME_TAKEN, "name_taken")
            return
        slug = slugify(name)
        others = self.plans.names_for_application(application_id, excluding=excluding)
        if slug and any(slugify(other) == slug for other in others):
            _add(errors, "name", SIMILAR_NAME_TAKEN, "name_taken")

    def _saved(self, write: Callable[[], BackupPlan]) -> BackupPlan:
        try:
            with transaction.atomic():
                return write()
        except IntegrityError as exc:
            raise ValidationError(
                {"name": [ErrorDetail(NAME_TAKEN, code="name_taken")]}
            ) from exc
