from __future__ import annotations

import itertools
import json
import os
import re
import shlex
import sys
from dataclasses import dataclass, field
from pathlib import Path

from . import extras
from .conf import setting
from .container import FORMAT_VERSION, read_format_version
from .container.format import container_version
from .exceptions import DBSError
from .io import write_new
from .naming import BACKUP_SUFFIX

OK = "ok"
ACTION = "action"
WARN = "warn"
FIXED = "fixed"
SKIP = "skip"

MIDDLEWARE_PATH = "dbs.security.middleware.DBSSecurityMiddleware"

PYPI = "https://pypi.org/pypi/django-dbs"
VERSION_PATTERN = re.compile(r"\d+(\.\d+){0,3}((a|b|rc)\d+)?(\.post\d+)?(\.dev\d+)?")
CHECKOUT_MARKERS = ("pyproject.toml", "setup.py", ".git")
PROJECT_FILES = (
    "requirements.in",
    "pyproject.toml",
    "setup.cfg",
    "Pipfile",
    "Pipfile.lock",
    "poetry.lock",
    "uv.lock",
    "pdm.lock",
)


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

    def ok(self, message, remedy=""):
        return Finding(self.name, self.since, OK, message, remedy)

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


class ScheduleInDatabase(Step):
    name = "backup schedule"
    since = "0.5.0"

    def check(self):
        from django.conf import settings
        from django.db import DatabaseError

        from .models import BackupSchedule
        from .schedule_runner import COMMAND, mode

        try:
            schedule = BackupSchedule.objects.order_by("pk").first()
        except DatabaseError:
            return self.warn("the backup schedule table is not migrated yet")
        if schedule is not None and schedule.enabled:
            return self.ok(f"backups run every {schedule.interval} from the DBS panel")
        if hasattr(settings, "DBS_SCHEDULE_INTERVAL"):
            return self.warn(
                "DBS_SCHEDULE_INTERVAL is set, but the frequency is now set in the DBS panel",
                "turn the schedule on at /admin/dbs/backupschedule/",
            )
        if mode() == COMMAND:
            return self.warn(
                "`dbs schedule` follows the DBS panel, where scheduled backups are off, "
                "so it takes none",
                "turn the schedule on at /admin/dbs/backupschedule/, or run "
                "`dbs schedule --interval 24h` to keep a fixed interval",
            )
        return self.ok("scheduled backups are off; turn them on at /admin/dbs/backupschedule/")


class SchedulerMode(Step):
    name = "scheduler"
    since = "0.5.0"

    def check(self):
        from .schedule_runner import MODES, THREAD, mode

        current = mode()
        if current not in MODES:
            return self.action(
                f"DBS_SCHEDULER is {current!r}, which DBS does not know",
                'DBS_SCHEDULER = "thread"  # or "command" or "off"',
            )
        if current == THREAD and _uwsgi_without_threads():
            return self.warn(
                "uWSGI runs without --enable-threads, so the schedule thread cannot start",
                'add --enable-threads, or set DBS_SCHEDULER = "command" and run '
                "python manage.py dbs schedule",
            )
        return self.ok(f"the schedule runs in {current} mode")


def _uwsgi_without_threads():
    try:
        import uwsgi
    except ImportError:
        return False
    options = getattr(uwsgi, "opt", {}) or {}
    return not (options.get("enable-threads") or options.get(b"enable-threads"))


class BackupDirectory(Step):
    name = "backup directory"
    since = "0.5.0"

    def check(self):
        from .io import can_write_into
        from .schedule_runner import backup_directory

        directory = backup_directory()
        if not directory:
            return self.warn(
                "DBS_BACKUP_DIR is not set, so the panel cannot schedule backups, restore "
                "a stored backup or report backup health",
                'DBS_BACKUP_DIR = BASE_DIR / "backups"',
            )
        if not can_write_into(directory):
            return self.warn(
                f"{directory} is not writable by this user, so scheduled backups will fail",
                'DBS_BACKUP_DIR = BASE_DIR / "backups"  # or a folder this user can write',
            )
        return self.ok(f"backups are kept in {directory}")


class Dependencies(Step):
    name = "dependencies"
    since = "0.7.0"

    def check(self):
        failure = extras.import_failure("numpy")
        if failure is None:
            return self.ok("numpy is installed for the Reed-Solomon parity")
        return self.action(
            f"numpy cannot be imported ({failure}), so backups cannot compute their "
            "Reed-Solomon parity",
            f'pip install --upgrade "{extras.DISTRIBUTION}>=0.7"',
        )


class GuardExtra(Step):
    name = "guard extra"
    since = "0.7.0"

    def check(self):
        if MIDDLEWARE_PATH not in (setting("MIDDLEWARE", ()) or ()):
            return self.ok("the session guard is off, so scikit-learn is not needed")
        failure = extras.import_error("guard")
        if failure is None:
            return self.ok("scikit-learn is installed for the session guard")
        return self.action(
            f"DBSSecurityMiddleware is on, but scikit-learn cannot be imported ({failure}), "
            "so the session guard runs without its anomaly detector",
            extras.install_command("guard"),
        )


class ManagerExtra(Step):
    name = "manager extra"
    since = "0.7.0"

    def check(self):
        absent = extras.missing("manager")
        if not absent:
            return self.ok("the DBS manager can run here (django_dbs run)")
        return self.ok(
            f"the DBS manager is not installed here ({', '.join(absent)} missing); "
            "this project does not need it",
            f"to run django_dbs on this machine: {extras.install_command('manager')}",
        )


class ManagerKeychain(Step):
    name = "manager keychain"
    since = "0.7.0"

    def check(self):
        if extras.missing("manager"):
            return self.ok(
                "the DBS manager does not run here, so it keeps no sealing key; "
                "the manager extra names what it needs"
            )
        return self.ok(
            "keyring is available, so the DBS manager keeps its sealing key in "
            "the system keychain wherever one works"
        )


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

        from .security.checks import AUTH_MIDDLEWARE, runs_before_authentication

        if runs_before_authentication():
            return self.warn(
                "DBSSecurityMiddleware runs before AuthenticationMiddleware, so the session "
                "guard never sees a signed-in user and scores nothing",
                f'move "{MIDDLEWARE_PATH}" below "{AUTH_MIDDLEWARE}" in MIDDLEWARE',
            )
        if MIDDLEWARE_PATH in (setting("MIDDLEWARE", ()) or ()):
            return self.ok("the session guard is active")
        if not apps.is_installed("django.contrib.admin"):
            return self.ok("no control panel, so the guard is not needed")
        return self.warn(
            "the control panel is reachable but nothing is scoring requests",
            f'MIDDLEWARE = [..., "{MIDDLEWARE_PATH}"]',
        )


class ForwardedFor(Step):
    name = "forwarded addresses"
    since = "0.7.0"

    def check(self):
        from .security.features import trusted_proxies

        configured = setting("DBS_TRUSTED_PROXIES", None)
        trusting = bool(setting("DBS_TRUST_FORWARDED_FOR", False))
        if isinstance(configured, (int, float)) and not isinstance(configured, bool):
            return self.warn(
                f"DBS_TRUSTED_PROXIES is the number {configured}; since 0.7.0 it lists the "
                "proxy networks, and the guard trusts X-Forwarded-For only from them",
                'DBS_TRUSTED_PROXIES = ["10.0.0.0/24"]  # the networks your proxies are in',
            )
        if trusting and not trusted_proxies():
            return self.warn(
                "DBS_TRUST_FORWARDED_FOR is on but DBS_TRUSTED_PROXIES names no proxy "
                "network, so the guard ignores X-Forwarded-For",
                'DBS_TRUSTED_PROXIES = ["10.0.0.0/24"]  # the networks your proxies are in',
            )
        if trusting:
            return self.ok("X-Forwarded-For is trusted only from DBS_TRUSTED_PROXIES")
        return self.ok("the guard scores the direct peer address")


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
                "DBS_RESTORE_ROOTS is empty, so file restores will refuse every path "
                "outside the file fields' storage and ModelBackup.file_roots",
                "List the directories a restore may write into, or unset it",
            )
        return self.ok("restores are confined to DBS_RESTORE_ROOTS")


class UnmanagedModels(Step):
    name = "unmanaged models"
    since = "0.7.0"

    def check(self):
        from .introspect import unmanaged_models_left_out
        from .registry import backup_registry

        if not backup_registry.is_empty():
            return self.ok("backup_registry chooses the models, so an unmanaged one is backed up when registered")
        left_out = sorted(model._meta.label_lower for model in unmanaged_models_left_out())
        if not left_out:
            return self.ok("no unmanaged model is left out of backups")
        return self.ok(
            "since 0.7.0 backups leave out unmanaged models (managed = False): "
            + ", ".join(left_out)
            + "; list '-app.model' in DBS_EXCLUDE_MODELS or register one to keep backing it up"
        )


class SourceFiles(Step):
    name = "missing source files"
    since = "0.7.0"

    def check(self):
        return self.ok(
            "since 0.7.0 a backup stops and names every source file it cannot read; "
            "pass --allow-missing-files (allow_missing_files=True) to back up without them"
        )


class BackupPaths(Step):
    name = "backup paths"
    since = "0.7.0"

    def check(self):
        return self.ok(
            "since 0.7.0 dbs backup PATH and create_backup(output=PATH) refuse a PATH that "
            "already exists; a script that reuses one name must choose a new one each run"
        )


class RestorePathMap(Step):
    name = "restore path map"
    since = "0.7.0"

    def check(self):
        from .exceptions import ConfigurationError
        from .files import is_inside, restore_path_map, restore_roots

        try:
            path_map = restore_path_map()
        except ConfigurationError as exc:
            return self.warn(str(exc), 'DBS_RESTORE_PATH_MAP = {"/old/root": "/new/root"}')
        if not path_map:
            return self.ok("no restore path map is configured")
        roots = restore_roots()
        unreachable = sorted(
            new
            for new in path_map.values()
            if not any(is_inside(os.path.realpath(new), root) for root in roots)
        )
        if unreachable:
            return self.warn(
                "DBS_RESTORE_PATH_MAP sends files to "
                + ", ".join(unreachable)
                + ", which no restore root allows, so those files would be refused",
                "Add those directories to DBS_RESTORE_ROOTS (or DBS_FILE_ROOTS)",
            )
        return self.ok("every new root in DBS_RESTORE_PATH_MAP is inside a restore root")


class RemoteCommandLimits(Step):
    name = "remote command limits"
    since = "0.7.0"

    def check(self):
        from .transports.ssh import DEFAULT_COMMAND_TIMEOUT, DEFAULT_KEEPALIVE_INTERVAL

        return self.ok(
            "since 0.7.0 an SSH connection sends a keepalive every "
            f"{DEFAULT_KEEPALIVE_INTERVAL:g} seconds and a remote command stops after "
            f"{DEFAULT_COMMAND_TIMEOUT / 3600:g} hours; an SSHTarget that runs longer "
            "commands sets its own command_timeout"
        )


class BackupFormat(Step):
    name = "backup format"
    since = "0.7.0"
    settings = (
        ("DBS_KDF_TIME_COST", "UNTRUSTED_MAX_TIME_COST", ""),
        ("DBS_KDF_MEMORY_COST", "UNTRUSTED_MAX_MEMORY_COST", " KiB"),
    )

    def check(self):
        from .crypto import kdf

        refused = []
        for name, ceiling_name, unit in self.settings:
            value = setting(name, None)
            ceiling = getattr(kdf, ceiling_name)
            if value is None:
                continue
            try:
                number = int(value)
            except (TypeError, ValueError):
                refused.append(f"{name} = {value!r} is not a number")
                continue
            if number > ceiling:
                refused.append(f"{name} = {number}{unit} is above {ceiling}{unit}")
        if refused:
            return self.action(
                "format 2 backups refuse "
                + " and ".join(refused)
                + ", so every new backup would fail",
                f"DBS_KDF_TIME_COST = {kdf.UNTRUSTED_MAX_TIME_COST} and "
                f"DBS_KDF_MEMORY_COST = {kdf.UNTRUSTED_MAX_MEMORY_COST} at most, or unset them",
            )
        return self.ok(
            f"since 0.7.0 new backups are written in format {FORMAT_VERSION} and streamed "
            "with bounded memory; format 1 backups still restore and validate, and "
            "`dbs upgrade --backups DIR` converts them into new files beside the originals"
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


class ClientRetired(Step):
    name = "dbs-client"
    since = "0.7.0"
    config_paths = ("dbs-client.toml", "~/.config/dbs/client.toml")

    def _configs(self):
        candidates = [os.environ.get("DBS_CLIENT_CONFIG", ""), *self.config_paths]
        expanded = [os.path.expanduser(path) for path in candidates if path]
        return [path for path in dict.fromkeys(expanded) if os.path.isfile(path)]

    def check(self):
        found = self._configs()
        if not found:
            return self.ok("no dbs-client config is left to move")
        return self.warn(
            "dbs-client was removed, and "
            + ", ".join(found)
            + " still lists the servers it backed up",
            f"Install the manager on your own machine ({extras.install_command('manager')}), "
            "add each server with `django_dbs run` or `django_dbs server add`, and back it "
            "up from there",
        )


class PulledBackups(Step):
    name = "off-site copies"
    since = "0.7.0"
    removed_settings = (
        "DBS_SSH_TARGETS",
        "DBS_SCHEDULE_PUSH_TARGET",
        "DBS_SCHEDULE_KEEP_REMOTE",
        "DBS_ADMIN_CONSOLE_SHELL",
    )
    remedy = (
        "the DBS manager pulls backups from this server now: on your own machine run "
        f"{extras.install_command('manager')} and "
        "`django_dbs server add NAME --host HOST --user USER` for this server, then "
        "delete the settings listed here"
    )
    explicit_target = (
        "; code that read DBS_SSH_TARGETS through SSHTarget.from_settings builds "
        "SSHTarget(host=..., username=..., ...) from explicit values now"
    )

    def check(self):
        from django.conf import settings

        left = [name for name in self.removed_settings if hasattr(settings, name)]
        stored = self._stored_targets()
        removed = self._removed_targets() if stored is None else []
        stored = stored or []
        problems = []
        if stored:
            problems.append("the panel still holds the SFTP targets " + ", ".join(stored))
        if left:
            problems.append(", ".join(left) + " no longer do anything")
        if problems:
            return self.warn(
                "this server no longer pushes backups anywhere, but " + "; ".join(problems),
                self.remedy + (self.explicit_target if "DBS_SSH_TARGETS" in left else ""),
            )
        if removed:
            return self.ok(
                "0.7.0 removed the SFTP targets "
                + ", ".join(removed)
                + "; the DBS manager pulls backups now (`django_dbs server add`)"
            )
        return self.ok("backups stay on this server and the DBS manager pulls them")

    @staticmethod
    def _stored_targets():
        from django.db import DEFAULT_DB_ALIAS, DatabaseError, connections

        connection = connections[DEFAULT_DB_ALIAS]
        try:
            if "dbs_backuptarget" not in connection.introspection.table_names():
                return None
            table = connection.ops.quote_name("dbs_backuptarget")
            with connection.cursor() as cursor:
                cursor.execute(f"SELECT name, username, host, port FROM {table} ORDER BY name")
                rows = cursor.fetchall()
        except DatabaseError:
            return None
        return [f"{name} ({username}@{host}:{port})" for name, username, host, port in rows]

    @staticmethod
    def _removed_targets():
        from django.db import DatabaseError

        from .models import AuditEvent

        try:
            events = AuditEvent.objects.filter(action="target.remove").order_by("target_name")
            return [
                f"{event.target_name} ({event.data.get('username')}@{event.data.get('host')}"
                f":{event.data.get('port')})"
                for event in events
            ]
        except DatabaseError:
            return []


class AuditChain(Step):
    name = "audit chain"
    since = "0.7.0"
    fixable = True
    migration = ("dbs", "0005_pull_only_retention_chain")

    def check(self):
        from django.db import DEFAULT_DB_ALIAS, DatabaseError, connections
        from django.db.migrations.recorder import MigrationRecorder

        try:
            applied = MigrationRecorder(connections[DEFAULT_DB_ALIAS]).applied_migrations()
        except DatabaseError as exc:
            return self.warn(f"could not read migration state: {exc}")
        if self.migration in applied:
            return self.ok(
                "every finished audit row is sealed in a hash chain; "
                "`manage.py dbs audit verify` checks it"
            )
        return self.action(
            "the audit trail cannot be sealed in a hash chain until dbs.0005 is applied",
            "python manage.py migrate dbs",
        )

    def fix(self):
        from django.core.management import call_command

        call_command("migrate", "dbs", verbosity=0)
        return self.fixed("applied the migration that seals the audit trail")


class ContribViewsRemoved(Step):
    name = "contrib views"
    since = "0.8.0"
    module = "dbs.contrib"

    def check(self):
        found = [name for name, source in _url_sources() if self.module in source]
        if not found:
            return self.ok("nothing refers to the removed dbs.contrib views")
        return self.action(
            "0.8.0 removed dbs.contrib, but " + ", ".join(found) + " still name it, "
            "so the project would not start",
            'delete include("dbs.contrib.urls"); take and restore backups at /admin/dbs/ '
            "or from the DBS manager",
        )


class CommandNames(Step):
    name = "command names"
    since = "0.8.0"
    retired = "dbs-upgrade"
    patterns = (
        "Makefile",
        "Procfile",
        "Dockerfile*",
        "Containerfile*",
        "*compose*.yml",
        "*compose*.yaml",
        "*.sh",
        ".github/workflows/*.yml",
        ".github/workflows/*.yaml",
    )

    def check(self):
        root = project_folder()
        mentions = sorted(
            {
                str(path.relative_to(root))
                for pattern in self.patterns
                for path in root.glob(pattern)
                if _mentions(path, self.retired)
            }
        )
        if not mentions:
            return self.ok(
                "manage.py dbs, manage.py django_dbs and manage.py django-dbs are the same "
                "command"
            )
        return self.warn(
            f"0.8.0 removed the {self.retired} command name, which "
            + ", ".join(mentions)
            + " still run",
            "use `python manage.py dbs upgrade` instead",
        )


class LegacyPartials(Step):
    name = "old partial files"
    since = "0.8.0"
    suffix = ".part"

    def check(self):
        from .naming import is_backup_name
        from .schedule_runner import backup_directory

        directory = backup_directory()
        try:
            names = sorted(os.listdir(directory)) if directory else []
        except OSError:
            names = []
        left = [
            name
            for name in names
            if name.endswith(self.suffix) and is_backup_name(name[: -len(self.suffix)])
        ]
        if not left:
            return self.ok("no partial file from before 0.7 is left in DBS_BACKUP_DIR")
        shown = " ".join(shlex.quote(os.path.join(directory, name)) for name in left[:20])
        return self.warn(
            f"{len(left)} partial file(s) left by a backup before 0.7 sit in {directory}; "
            "they are no backups and DBS no longer sweeps them",
            f"rm {shown}" + (" ..." if len(left) > 20 else ""),
        )


class SSHTargetKeys(Step):
    name = "ssh target keys"
    since = "0.8.0"

    def check(self):
        return self.ok(
            "SSHTarget.from_dict reads username and key_filename; the old user and key_file "
            "names are refused"
        )


class KeepAtMostFive(Step):
    name = "retention"
    since = "0.7.0"

    def check(self):
        from django.db import DatabaseError

        from .models import BackupSchedule
        from .retention import MAXIMUM_KEEP

        problems = []
        configured = setting("DBS_SCHEDULE_KEEP", None)
        if configured is not None and not self._within(configured, MAXIMUM_KEEP):
            problems.append(f"DBS_SCHEDULE_KEEP is {configured}")
        try:
            kept = BackupSchedule.objects.order_by("pk").values_list("keep", flat=True).first()
        except DatabaseError:
            kept = None
        if kept is not None and kept > MAXIMUM_KEEP:
            problems.append(f"the panel's schedule keeps {kept}, which migrate lowers to 5")
        if problems:
            return self.warn(
                f"the server now keeps at most {MAXIMUM_KEEP} backups in DBS_BACKUP_DIR, but "
                + "; ".join(problems),
                f"DBS_SCHEDULE_KEEP = {MAXIMUM_KEEP}  # dbs schedule refuses larger values",
            )
        return self.ok(f"the server keeps at most {MAXIMUM_KEEP} backups")

    @staticmethod
    def _within(value, maximum):
        try:
            return 1 <= int(value) <= maximum
        except (TypeError, ValueError):
            return False


STEPS = (
    InstalledApp,
    Migrations,
    ScheduleInDatabase,
    SchedulerMode,
    BackupDirectory,
    Dependencies,
    GuardExtra,
    ManagerExtra,
    ManagerKeychain,
    AdminPanel,
    GuardMiddleware,
    ForwardedFor,
    ExcludeSemantics,
    Passphrase,
    RestoreRoots,
    UnmanagedModels,
    SourceFiles,
    BackupPaths,
    RestorePathMap,
    RemoteCommandLimits,
    BackupFormat,
    AiInstructions,
    ClientRetired,
    PulledBackups,
    KeepAtMostFive,
    AuditChain,
    ContribViewsRemoved,
    CommandNames,
    LegacyPartials,
    SSHTargetKeys,
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


def package_directory() -> Path:
    from . import __file__ as package_file

    return Path(package_file).resolve().parent


def installed_distribution():
    from importlib import metadata

    try:
        return metadata.distribution(extras.DISTRIBUTION)
    except metadata.PackageNotFoundError:
        return None


def installed_as_editable(distribution) -> bool:
    raw = distribution.read_text("direct_url.json")
    if not raw:
        return False
    try:
        return bool(json.loads(raw).get("dir_info", {}).get("editable"))
    except (ValueError, AttributeError):
        return False


def is_source_checkout(package_dir: Path, distribution) -> bool:
    if distribution is None:
        return True
    if any((package_dir.parent / marker).exists() for marker in CHECKOUT_MARKERS):
        return True
    if installed_as_editable(distribution):
        return True
    return Path(distribution.locate_file("dbs")).resolve() != package_dir


def is_editable_install() -> bool:
    return is_source_checkout(package_directory(), installed_distribution())


def is_system_interpreter(prefix: str | None = None, base_prefix: str | None = None) -> bool:
    prefix = Path(prefix or sys.prefix)
    base_prefix = Path(base_prefix or getattr(sys, "base_prefix", sys.prefix))
    if prefix.resolve() != base_prefix.resolve():
        return False
    return not (prefix / "conda-meta").is_dir()


def is_version(text: str) -> bool:
    return bool(VERSION_PATTERN.fullmatch(text or ""))


def pinned_install_command(version: str, installed_extras=()) -> list:
    return [
        sys.executable,
        "-m",
        "pip",
        "install",
        extras.requirement(sorted(installed_extras), version),
    ]


def project_folder() -> Path:
    base = setting("BASE_DIR", None)
    return Path(base) if base else Path.cwd()


def _mentions(path: Path, text: str) -> bool:
    try:
        return path.is_file() and text in path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False


def _module_source(name: str) -> str | None:
    import importlib.util

    try:
        spec = importlib.util.find_spec(name)
    except (ImportError, ValueError):
        return None
    if spec is None or not spec.origin or not os.path.isfile(spec.origin):
        return None
    try:
        return Path(spec.origin).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _url_sources():
    from django.apps import apps
    from django.conf import settings

    names = [getattr(settings, "ROOT_URLCONF", "") or ""]
    names += [f"{config.name}.urls" for config in apps.get_app_configs()]
    for name in dict.fromkeys(name for name in names if name and not name.startswith("dbs.")):
        source = _module_source(name)
        if source is not None:
            yield name, source


def requirement_files(root: Path) -> list:
    candidates = sorted(root.glob("requirements*.txt")) + sorted(root.glob("requirements/*.txt"))
    candidates += [root / name for name in PROJECT_FILES]
    found = []
    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8", errors="replace").lower()
        except OSError:
            continue
        if any(name in text for name in ("django-dbs", "django_dbs")):
            found.append(path)
    return found


def confirm_install(stream=None) -> bool:
    stream = stream or sys.stdin
    if not hasattr(stream, "isatty") or not stream.isatty():
        return False
    return input("Install it now? [y/N] ").strip().lower() in ("y", "yes")


def _pypi_json(path: str, timeout: float):
    import urllib.request

    with urllib.request.urlopen(f"{PYPI}/{path}", timeout=timeout) as response:
        return json.load(response)


def latest_release(timeout: float = 10.0) -> str | None:
    try:
        return _pypi_json("json", timeout)["info"]["version"]
    except Exception:
        return None


def release_exists(version: str, timeout: float = 10.0) -> bool | None:
    import urllib.error

    try:
        _pypi_json(f"{version}/json", timeout)
    except urllib.error.HTTPError as exc:
        return False if exc.code == 404 else None
    except Exception:
        return None
    return True


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


def _convert_format_1(data, passphrase):
    from .engine.convert import convert_v1

    return convert_v1(data, passphrase)


CONVERTERS: dict = {
    1: Converter(produces=FORMAT_VERSION, convert=_convert_format_1, needs_passphrase=True),
}


@dataclass
class BackupState:
    path: Path
    version: int | None
    converted_to: Path | None = None
    converted_earlier: bool = False
    error: str = ""

    @property
    def current(self):
        return self.version == FORMAT_VERSION

    @property
    def unreadable(self):
        return bool(self.error) or self.version is None


def inspect_backup(path: Path) -> BackupState:
    try:
        with path.open("rb") as handle:
            version = read_format_version(handle)
    except OSError as exc:
        return BackupState(path, None, error=f"cannot read the file: {exc}")
    if version is None:
        return BackupState(path, None, error="not a DBS container, or the header is destroyed")
    return BackupState(path, version)


class ConversionRejected(Exception):
    pass


def conversion_name(path: Path, version: int, copy: int = 1) -> Path:
    name = path.name
    stem = name[: -len(BACKUP_SUFFIX)] if name.endswith(BACKUP_SUFFIX) else name
    marker = f".v{version}" if copy <= 1 else f".v{version}-{copy}"
    return path.with_name(f"{stem}{marker}{BACKUP_SUFFIX}")


def conversion_names(path: Path, version: int):
    return (conversion_name(path, version, copy) for copy in itertools.count(1))


def existing_conversion(path: Path) -> Path | None:
    for candidate in conversion_names(path, FORMAT_VERSION):
        if not candidate.exists():
            return None
        if inspect_backup(candidate).current:
            return candidate
    return None


def require_valid(data: bytes, passphrase: str | None) -> None:
    from .engine import validate_backup

    version = container_version(data)
    if version != FORMAT_VERSION:
        raise ConversionRejected(f"it is format version {version}, not {FORMAT_VERSION}")
    result = validate_backup(data, passphrase)
    if not result.ok:
        raise ConversionRejected(result.summary())


def convert_backup(state: BackupState, passphrase: str | None) -> BackupState:
    earlier = existing_conversion(state.path)
    if earlier is not None:
        state.converted_to = earlier
        state.converted_earlier = True
        return state

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
        written = write_new(
            data,
            (str(name) for name in conversion_names(state.path, FORMAT_VERSION)),
            verify=lambda on_disk: require_valid(on_disk, passphrase),
        )
    except (ConversionRejected, DBSError) as exc:
        state.error = f"the converted file did not validate: {exc}"
        return state
    except OSError as exc:
        state.error = f"could not write the converted file: {exc}"
        return state
    state.converted_to = Path(written)
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
