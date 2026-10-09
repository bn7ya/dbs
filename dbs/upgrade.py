from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .conf import setting
from .container.format import FORMAT_VERSION, container_version
from .exceptions import DBSError

OK = "ok"
ACTION = "action"
WARN = "warn"
FIXED = "fixed"
SKIP = "skip"

MIDDLEWARE_PATH = "dbs.security.middleware.DBSSecurityMiddleware"


@dataclass
class Finding:
    step: str
    since: str
    level: str
    message: str
    remedy: str = ""


@dataclass
class Report:
    findings: list = field(default_factory=list)

    def add(self, finding):
        self.findings.append(finding)
        return finding

    @property
    def outstanding(self):
        return [f for f in self.findings if f.level in (ACTION, WARN)]

    @property
    def blocked(self):
        return any(f.level == ACTION for f in self.findings)


class Step:
    name = ""
    since = ""
    fixable = False

    def check(self) -> Finding:
        raise NotImplementedError

    def fix(self) -> Finding:
        raise NotImplementedError

    def ok(self, message):
        return Finding(self.name, self.since, OK, message)

    def action(self, message, remedy=""):
        return Finding(self.name, self.since, ACTION, message, remedy)

    def warn(self, message, remedy=""):
        return Finding(self.name, self.since, WARN, message, remedy)

    def fixed(self, message):
        return Finding(self.name, self.since, FIXED, message)


class InstalledApp(Step):
    name = "installed app"
    since = "0.1.0"

    def check(self):
        from django.apps import apps

        if apps.is_installed("dbs"):
            return self.ok("dbs is in INSTALLED_APPS")
        return self.action(
            "dbs is not in INSTALLED_APPS, so nothing else here can work",
            'INSTALLED_APPS = [..., "dbs"]',
        )


class Migrations(Step):
    name = "migrations"
    since = "0.3.0"
    fixable = True

    def _pending(self):
        from django.db import DEFAULT_DB_ALIAS, connections
        from django.db.migrations.executor import MigrationExecutor

        executor = MigrationExecutor(connections[DEFAULT_DB_ALIAS])
        targets = executor.loader.graph.leaf_nodes("dbs")
        return executor.migration_plan(targets)

    def check(self):
        try:
            pending = self._pending()
        except Exception as exc:
            return self.warn(f"could not read migration state: {exc}")
        if not pending:
            return self.ok("dbs migrations are applied")
        own = [m for m, _ in pending if m.app_label == "dbs"]
        others = len(pending) - len(own)
        detail = f"{len(own)} dbs migration(s) are not applied"
        if others:
            detail += f", and {others} migration(s) they depend on"
        return self.action(detail, "python manage.py migrate dbs")

    def fix(self):
        from django.core.management import call_command

        call_command("migrate", "dbs", verbosity=0)
        return self.fixed("applied the pending dbs migrations")


class AuditTrail(Step):
    name = "audit trail"
    since = "0.5.0"
    fixable = True
    migration = ("dbs", "0003_audit_outcome")

    def check(self):
        from django.db import DEFAULT_DB_ALIAS, DatabaseError, connections
        from django.db.migrations.recorder import MigrationRecorder

        try:
            applied = MigrationRecorder(connections[DEFAULT_DB_ALIAS]).applied_migrations()
        except DatabaseError as exc:
            return self.warn(f"could not read migration state: {exc}")
        if self.migration in applied:
            return self.ok("backups, restores and validations record their outcome")
        return self.action(
            "the audit trail cannot record outcomes until dbs.0003 is applied",
            "python manage.py migrate dbs",
        )

    def fix(self):
        from django.core.management import call_command

        call_command("migrate", "dbs", verbosity=0)
        return self.fixed("applied the audit trail migration")


class Dependencies(Step):
    name = "dependencies"
    since = "0.3.0"

    def check(self):
        try:
            import sklearn  # noqa: F401
        except ImportError:
            return self.action(
                "scikit-learn is missing, so the session guard cannot score anything",
                'pip install "django-dbs>=0.3"',
            )
        return self.ok("scikit-learn is available")


class AdminPanel(Step):
    name = "admin panel"
    since = "0.3.0"

    def check(self):
        from django.apps import apps

        if apps.is_installed("django.contrib.admin"):
            return self.ok("the control panel is mounted at /admin/dbs/")
        return self.warn(
            "django.contrib.admin is not installed, so there is no control panel",
            'INSTALLED_APPS = [..., "django.contrib.admin", "dbs"]',
        )


class GuardMiddleware(Step):
    name = "session guard"
    since = "0.3.0"

    def check(self):
        from django.apps import apps

        if MIDDLEWARE_PATH in (setting("MIDDLEWARE", ()) or ()):
            return self.ok("the session guard is active")
        if not apps.is_installed("django.contrib.admin"):
            return self.ok("no control panel, so the guard is not needed")
        return self.warn(
            "the control panel is reachable but nothing is scoring requests",
            f'MIDDLEWARE = [..., "{MIDDLEWARE_PATH}"]',
        )


class ExcludeSemantics(Step):
    name = "excluded models"
    since = "0.2.2"

    def check(self):
        from .introspect import DEFAULT_EXCLUDES

        configured = setting("DBS_EXCLUDE_MODELS", None) or ()
        restated = [
            label
            for label in configured
            if str(label).lower().lstrip("-") in DEFAULT_EXCLUDES
            and not str(label).startswith("-")
        ]
        if not restated:
            return self.ok("DBS_EXCLUDE_MODELS reads as current")
        return self.warn(
            "DBS_EXCLUDE_MODELS restates "
            + ", ".join(restated)
            + ", which DBS already excludes. Before 0.2.2 the setting replaced the "
            "defaults; now it extends them",
            "Drop those entries, or prefix one with '-' to back it up deliberately",
        )


class Passphrase(Step):
    name = "passphrase"
    since = "0.3.0"

    def check(self):
        from .keys import has_default_passphrase

        if setting("DBS_PASSPHRASE", None) or os.environ.get("DBS_PASSPHRASE"):
            return self.ok("an explicit DBS_PASSPHRASE is configured")
        if has_default_passphrase():
            return self.ok("the passphrase is derived from SECRET_KEY")
        return self.action(
            "no passphrase can be derived: SECRET_KEY is empty and DBS_PASSPHRASE is unset",
            "Set SECRET_KEY, or export DBS_PASSPHRASE",
        )


class RestoreRoots(Step):
    name = "restore roots"
    since = "0.3.0"

    def check(self):
        file_roots = setting("DBS_FILE_ROOTS", None) or ()
        restore_roots = setting("DBS_RESTORE_ROOTS", None)
        if not file_roots:
            return self.ok("no extra file roots are configured")
        if restore_roots is None:
            return self.ok("restores are confined to DBS_FILE_ROOTS")
        if not restore_roots:
            return self.warn(
                "DBS_RESTORE_ROOTS is empty, so file restores will refuse every path",
                "List the directories a restore may write into, or unset it",
            )
        return self.ok("restores are confined to DBS_RESTORE_ROOTS")


class HiddenRows(Step):
    name = "hidden rows"
    since = "0.4.0"

    def _filtered_models(self):
        from .introspect import config_for, discover_models
        from .registry import ModelBackup, backup_registry

        filtered = []
        for model in discover_models(backup_registry):
            config = config_for(backup_registry, model)
            if type(config).get_queryset is not ModelBackup.get_queryset:
                continue
            if str(model._default_manager.all().query) != str(model._base_manager.all().query):
                filtered.append(model._meta.label_lower)
        return filtered

    def check(self):
        try:
            filtered = self._filtered_models()
        except Exception as exc:
            return self.warn(f"could not inspect the default managers: {exc}")
        if not filtered:
            return self.ok("no backed-up model has a default manager that hides rows")
        return self.ok(
            "since 0.4.0 backups include the rows hidden by the default manager of "
            + ", ".join(filtered)
            + "; override ModelBackup.get_queryset to leave them out"
        )


class AiInstructions(Step):
    name = "ai instructions"
    since = "0.3.1"
    fixable = True

    def _stale(self):
        from .management.commands.dbs_ai import shipped_files

        root = Path.cwd()
        if not (root / ".claude").exists():
            return None
        return [
            (root / relative, source)
            for relative, source in shipped_files().items()
            if not (root / relative).is_file()
            or (root / relative).read_text(encoding="utf-8")
            != source.read_text(encoding="utf-8")
        ]

    def check(self):
        stale = self._stale()
        if stale is None:
            return self.ok("no installed AI instructions to keep current")
        if not stale:
            return self.ok("the installed AI instructions match this version")
        return self.action(
            f"{len(stale)} installed AI instruction file(s) are out of date",
            "python manage.py dbs ai",
        )

    def fix(self):
        stale = self._stale() or []
        for destination, source in stale:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        return self.fixed(f"refreshed {len(stale)} AI instruction file(s)")


STEPS = (
    InstalledApp,
    Migrations,
    AuditTrail,
    Dependencies,
    AdminPanel,
    GuardMiddleware,
    ExcludeSemantics,
    Passphrase,
    RestoreRoots,
    HiddenRows,
    AiInstructions,
)


def run_steps(*, apply_fixes: bool) -> Report:
    report = Report()
    for step_class in STEPS:
        step = step_class()
        finding = step.check()
        if finding.level == ACTION and apply_fixes and step.fixable:
            try:
                finding = step.fix()
            except Exception as exc:
                finding = step.action(f"{finding.message} (fix failed: {exc})", finding.remedy)
        report.add(finding)
    return report


def installed_version() -> str:
    from . import __version__

    return __version__


def is_editable_install() -> bool:
    from . import __file__ as package_file

    return "site-packages" not in str(Path(package_file).resolve())


def latest_release(timeout: float = 10.0) -> str | None:
    import json
    import urllib.request

    try:
        with urllib.request.urlopen(
            "https://pypi.org/pypi/django-dbs/json", timeout=timeout
        ) as response:
            return json.load(response)["info"]["version"]
    except Exception:
        return None


def _as_numbers(version: str):
    parts = []
    for chunk in version.split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def is_newer(candidate: str, current: str) -> bool:
    return _as_numbers(candidate) > _as_numbers(current)


@dataclass
class Converter:
    produces: int
    convert: object
    needs_passphrase: bool = False


CONVERTERS: dict = {}


@dataclass
class BackupState:
    path: Path
    version: int | None
    converted_to: Path | None = None
    error: str = ""

    @property
    def current(self):
        return self.version == FORMAT_VERSION

    @property
    def unreadable(self):
        return bool(self.error) or self.version is None


def inspect_backup(path: Path) -> BackupState:
    try:
        data = path.read_bytes()
    except OSError as exc:
        return BackupState(path, None, error=f"cannot read the file: {exc}")
    version = container_version(data)
    if version is None:
        return BackupState(path, None, error="not a DBS container, or the header is destroyed")
    return BackupState(path, version)


def convert_backup(state: BackupState, passphrase: str | None) -> BackupState:
    from .engine import validate_backup

    data = state.path.read_bytes()
    version = state.version
    hops = 0
    while version != FORMAT_VERSION:
        converter = CONVERTERS.get(version)
        if converter is None:
            state.error = (
                f"format version {version} has no converter in this build"
                if version is not None
                else "the container version could not be determined"
            )
            return state
        try:
            data = converter.convert(data, passphrase)
        except Exception as exc:
            state.error = f"converting from version {version} failed: {exc}"
            return state
        version = container_version(data)
        hops += 1
        if hops > len(CONVERTERS) + 1:
            state.error = "the converters do not reach the current format"
            return state

    try:
        result = validate_backup(data, passphrase)
    except DBSError as exc:
        state.error = f"the converted file did not validate: {exc}"
        return state
    if not result.ok:
        state.error = f"the converted file did not validate: {result.summary()}"
        return state

    destination = state.path.with_name(state.path.name + ".converted")
    destination.write_bytes(data)
    state.converted_to = destination
    state.version = FORMAT_VERSION
    return state


def read_backup_states(directory: Path) -> list:
    return [inspect_backup(path) for path in sorted(directory.glob("*.dbs"))]


def abandonment_phrase(count: int) -> str:
    return f"abandon {count} backup{'s' if count != 1 else ''}"


def confirm_abandonment(count: int, stream=None) -> bool:
    stream = stream or sys.stdin
    if not hasattr(stream, "isatty") or not stream.isatty():
        return False
    typed = input(f'Type "{abandonment_phrase(count)}" to continue: ').strip()
    return typed == abandonment_phrase(count)
