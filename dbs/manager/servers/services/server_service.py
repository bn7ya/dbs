from __future__ import annotations

import json
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import QuerySet
from django.utils import timezone
from rest_framework.exceptions import ErrorDetail, NotFound, ValidationError

from dbs.manager.accounts.services import AccountService
from dbs.manager.activity.services import ActivityService
from dbs.manager.common.exceptions import error_code_of
from dbs.manager.common.paths import absolute_path
from dbs.manager.servers import keys, versions
from dbs.manager.servers.exceptions import (
    HostKeyChanged,
    NoPrivateKey,
    RemoteCommandFailed,
    SSHAuthFailed,
    SSHUnreachable,
)
from dbs.manager.servers.gateways import (
    HostKey,
    RemoteHost,
    fetch_host_key,
    parse_host_key,
)
from dbs.manager.servers.models import Server
from dbs.manager.servers.repositories import ServerRepository
from dbs.manager.servers.services import pythons, vault_contexts
from dbs.manager.servers.services.connection_service import ServerConnectionService
from dbs.manager.vault import seal_text

if TYPE_CHECKING:
    from django.contrib.auth.models import AnonymousUser, User

PLAIN_FIELDS = (
    "name",
    "host",
    "port",
    "username",
    "python_path",
    "manage_path",
    "settings_module",
)
OPTIONAL_PATH_FIELDS = ("project_dir", "env_path")
REQUIRED_PATH_FIELDS = ("remote_backup_dir",)
UNGUARDED_FIELDS = frozenset({"name"})
SETUP_FIELDS = frozenset(
    {
        "project_dir",
        "python_path",
        "manage_path",
        "settings_module",
        "remote_backup_dir",
        "file_roots",
        "env_path",
    }
)
SETUP_WINDOW = timedelta(hours=1)
HEALTH_STATUSES = ("ok", "warn", "error")

CONNECTION_ERRORS = (HostKeyChanged, SSHAuthFailed, SSHUnreachable)
DBS_VERSION = pythons.VERSION_PROBE
REPORTED_OUTPUT_LIMIT = 200

INVALID_HOST_KEY = "Paste the host key as one line, for example 'ssh-ed25519 AAAA...'."
ABSOLUTE_PATH_REQUIRED = (
    "Use an absolute path that starts with / and has no '..' in it."
)
NAME_TAKEN = "Another server already has this name."
PRIVATE_KEY_REQUIRED = "Paste the private key this server accepts."
PASSWORD_REQUIRED = "Enter the password this server accepts."
ACCOUNT_PASSWORD_REQUIRED = "Enter your own password to change this."

Errors = dict[str, list[ErrorDetail]]


class Action:
    CREATE = "server.create"
    UPDATE = "server.update"
    DELETE = "server.delete"
    CHECK = "server.check"
    REPIN = "server.repin"
    PASSPHRASE_REVEAL = "server.passphrase_reveal"
    FINGERPRINT = "server.fingerprint"
    KEYPAIR = "server.keypair"
    PASSPHRASE_CAPTURE = "server.passphrase_capture"


def _add(errors: Errors, field: str, message: str, code: str) -> None:
    errors.setdefault(field, []).append(ErrorDetail(message, code=code))


def _address(host: str, port: int) -> str:
    return f"[{host}]:{port}" if ":" in host else f"{host}:{port}"


def _changed(server: Server, changes: dict[str, Any]) -> list[str]:
    names = set()
    for column, value in changes.items():
        if column.endswith("_sealed"):
            if value is not None or getattr(server, column) is not None:
                names.add(column.removesuffix("_sealed"))
        elif getattr(server, column) != value:
            names.add(column)
    return sorted(names)


@dataclass(frozen=True)
class AddedServer:
    server: Server
    public_key: str | None = None
    authorized_keys_hint: str | None = None


@dataclass(frozen=True)
class CheckedServer:
    server: Server
    compatibility: dict[str, Any]


class ServerService:
    def __init__(self, user: User | AnonymousUser | None) -> None:
        self.user: User | AnonymousUser | None = user
        self.servers = ServerRepository()
        self.connections = ServerConnectionService(user)
        self.activity = ActivityService(user)

    def list(self, search: str | None = None) -> QuerySet[Server]:
        return self.servers.search((search or "").strip() or None)

    def with_env_path(self) -> QuerySet[Server]:
        return self.servers.with_env_path()

    def get(self, server_id: UUID) -> Server:
        server = self.servers.find(server_id)
        if server is None:
            raise NotFound()
        return server

    def fingerprint(self, host: str, port: int) -> HostKey:
        with self.activity.track(
            Action.FINGERPRINT, target=_address(host, port)
        ) as entry:
            key = fetch_host_key(host, port)
            entry.detail = {"fingerprint": key.fingerprint}
            return key

    def add(self, **data: Any) -> AddedServer:
        if not data.pop("generate_key", False):
            return AddedServer(server=self.create(**data))
        server, public_key = self.create_with_key(**data)
        return AddedServer(
            server=server,
            public_key=public_key,
            authorized_keys_hint=keys.authorized_keys_hint(public_key, server.username),
        )

    def create(self, **data: Any) -> Server:
        data.pop("generate_key", None)
        errors: Errors = {}
        fields = {name: data[name] for name in PLAIN_FIELDS if name in data}
        fields |= self._paths(data, errors)
        fields |= self._pinned(data["host_key"], errors)
        fields |= self._credentials(data, errors, data["auth_method"], current=None)
        if self.servers.name_in_use(data["name"]):
            _add(errors, "name", NAME_TAKEN, "name_taken")
        if errors:
            raise ValidationError(errors)

        fields["backup_passphrase_sealed"] = seal_text(
            data.get("backup_passphrase") or secrets.token_urlsafe(32),
            context=vault_contexts.BACKUP_PASSPHRASE,
        )
        with transaction.atomic():
            server = self._saved(
                lambda: self.servers.create(
                    created_by=cast("User | None", self.user), **fields
                )
            )
            self.activity.record(Action.CREATE, server=server, target=server.name)
        return server

    def create_with_key(self, **data: Any) -> tuple[Server, str]:
        private_key, public_key = keys.generate_keypair()
        data.update(
            auth_method=Server.AuthMethod.KEY,
            private_key=private_key,
            key_passphrase="",
        )
        with transaction.atomic():
            server = self.create(**data)
            self.activity.record(
                Action.KEYPAIR,
                server=server,
                target=server.name,
                detail={"fingerprint": keys.fingerprint(public_key)},
            )
        return server, public_key

    def public_key(self, server_id: UUID) -> str:
        server = self.get(server_id)
        credentials = self.connections.credentials(server)
        if not credentials.private_key:
            raise NoPrivateKey()
        try:
            return keys.public_key_of(
                credentials.private_key, credentials.key_passphrase
            )
        except keys.KeyUnreadable as exc:
            raise NoPrivateKey() from exc

    def update(
        self, server_id: UUID, account_password: str = "", **data: Any
    ) -> Server:
        server = self.get(server_id)
        errors: Errors = {}
        changes = {name: data[name] for name in PLAIN_FIELDS if name in data}
        changes |= self._paths(data, errors)
        changes |= self._credentials(
            data, errors, data.get("auth_method", server.auth_method), current=server
        )
        if "name" in data and self.servers.name_in_use(
            data["name"], excluding=server.pk
        ):
            _add(errors, "name", NAME_TAKEN, "name_taken")
        if errors:
            raise ValidationError(errors)

        if data.get("backup_passphrase"):
            changes["backup_passphrase_sealed"] = seal_text(
                data["backup_passphrase"], context=vault_contexts.BACKUP_PASSPHRASE
            )
        changed = _changed(server, changes)
        free = (
            UNGUARDED_FIELDS | SETUP_FIELDS
            if self.in_setup(server)
            else UNGUARDED_FIELDS
        )
        guarded = not free.issuperset(changed)
        if guarded and not account_password:
            raise ValidationError(
                {
                    "account_password": [
                        ErrorDetail(ACCOUNT_PASSWORD_REQUIRED, code="required"),
                    ]
                }
            )
        name = changes.get("name", server.name)
        with self.activity.track(Action.UPDATE, server=server, target=name) as entry:
            entry.detail = {"fields": changed}
            if guarded or account_password:
                AccountService(self.user).confirm_password(account_password)
            return self._saved(lambda: self.servers.update(server, **changes))

    def require_step_up(self, server: Server, account_password: str) -> None:
        if not account_password and not self.in_setup(server):
            raise ValidationError(
                {
                    "account_password": [
                        ErrorDetail(ACCOUNT_PASSWORD_REQUIRED, code="required"),
                    ]
                }
            )

    def confirm_step_up(self, account_password: str) -> None:
        if account_password:
            AccountService(self.user).confirm_password(account_password)

    def in_setup(self, server: Server) -> bool:
        return (
            self.user is not None
            and self.user.is_authenticated
            and server.created_by_id == self.user.pk
            and server.created_at > timezone.now() - SETUP_WINDOW
            and server.last_check_status != Server.CheckStatus.OK
        )

    def delete(self, server_id: UUID) -> None:
        server = self.get(server_id)
        with transaction.atomic():
            self.servers.soft_delete(server)
            self.activity.record(Action.DELETE, server=server, target=server.name)

    def repin(self, server_id: UUID, host_key: str, password: str) -> Server:
        server = self.get(server_id)
        with self.activity.track(
            Action.REPIN, server=server, target=server.name
        ) as entry:
            AccountService(self.user).confirm_password(password)
            errors: Errors = {}
            pinned = self._pinned(host_key, errors)
            if errors:
                raise ValidationError(errors)
            entry.detail = {"fingerprint": pinned["host_key_fingerprint"]}
            return self.servers.update(
                server,
                **pinned,
                last_check_status=Server.CheckStatus.UNKNOWN,
                last_check_error="",
            )

    def reveal_passphrase(self, server_id: UUID, password: str) -> str:
        server = self.get(server_id)
        with self.activity.track(
            Action.PASSPHRASE_REVEAL, server=server, target=server.name
        ):
            AccountService(self.user).confirm_password(password)
            return self.connections.backup_passphrase(server)

    def check(self, server_id: UUID) -> Server:
        server = self.get(server_id)
        with self.activity.track(
            Action.CHECK, server=server, target=server.name
        ) as entry:
            try:
                with self.connections.open(server) as remote:
                    report = self._inspect(server, remote)
                    health = self._health(server, remote, report["dbs_version"])
            except CONNECTION_ERRORS as exc:
                self._record(server, Server.CheckStatus.FAILED, error_code_of(exc), {})
                entry.detail = {"status": Server.CheckStatus.FAILED}
                raise
            status = (
                Server.CheckStatus.OK if _ready(report) else Server.CheckStatus.PROBLEM
            )
            entry.detail = {"status": status}
            self.servers.update(server, last_health=health)
            return self._record(server, status, "", report)

    def checked(self, server_id: UUID) -> CheckedServer:
        server = self.check(server_id)
        return CheckedServer(server=server, compatibility=self.compatibility(server))

    def compatibility(self, server: Server) -> dict[str, Any]:
        remote = (server.last_check_report or {}).get("dbs_version")
        return versions.compatibility(remote)

    def capture_passphrase(self, server_id: UUID) -> Server:
        server = self.get(server_id)
        with self.activity.track(
            Action.PASSPHRASE_CAPTURE, server=server, target=server.name
        ):
            with self.connections.open(server) as remote:
                result = remote.run(
                    [server.python_path, server.manage_path, "dbs_key", "--show"],
                    cwd=server.project_dir or None,
                    env=_settings_env(server),
                )
            lines = result.stdout.strip().splitlines()
            if not result.ok or not lines or not lines[-1].strip():
                raise RemoteCommandFailed(output=result.stderr.strip()[-500:])
            sealed = seal_text(
                lines[-1].strip(), context=vault_contexts.BACKUP_PASSPHRASE
            )
            return self.servers.update(server, backup_passphrase_sealed=sealed)

    def _health(
        self, server: Server, remote: RemoteHost, remote_version: str | None
    ) -> dict[str, Any] | None:
        if not versions.at_least(remote_version, versions.HEALTH_FROM):
            return None
        try:
            result = remote.run(
                [server.python_path, server.manage_path, "dbs", "health", "--json"],
                cwd=server.project_dir or None,
                env=_settings_env(server),
            )
        except RemoteCommandFailed:
            return None
        return _health_report(result.stdout)

    def _inspect(self, server: Server, remote: RemoteHost) -> dict[str, Any]:
        project_dir = server.project_dir or None
        system = _output(remote, ["uname", "-sr"])
        probe = pythons.probe(remote, server.python_path, project_dir)
        dbs_version = probe.version
        backup_command = None
        if project_dir:
            env = (
                {"DJANGO_SETTINGS_MODULE": server.settings_module}
                if server.settings_module
                else None
            )
            backup_command = _succeeds(
                remote,
                [server.python_path, server.manage_path, "dbs_backup", "--help"],
                cwd=project_dir,
                env=env,
            )
        return {
            "system": system,
            "dbs_version": dbs_version,
            "dbs_error": probe.error,
            "python_suggestion": (
                None
                if dbs_version is not None or project_dir is None
                else _python_suggestion(server, remote, project_dir)
            ),
            "backup_command": backup_command,
            "env_file": _exists(remote, server.env_path) if server.env_path else None,
            "roots": {root: _exists(remote, root) for root in server.file_roots},
            "remote_backup_dir": _exists(remote, server.remote_backup_dir),
        }

    def _record(
        self, server: Server, status: str, error: str, report: dict[str, Any]
    ) -> Server:
        return self.servers.update(
            server,
            last_check_status=status,
            last_check_error=error,
            last_check_report=report,
            last_checked_at=timezone.now(),
        )

    def _paths(self, data: dict[str, Any], errors: Errors) -> dict[str, Any]:
        cleaned: dict[str, Any] = {}
        for name in (*OPTIONAL_PATH_FIELDS, *REQUIRED_PATH_FIELDS):
            if name not in data:
                continue
            if name in OPTIONAL_PATH_FIELDS and not data[name]:
                cleaned[name] = ""
            elif (path := absolute_path(data[name])) is not None:
                cleaned[name] = path
            else:
                _add(errors, name, ABSOLUTE_PATH_REQUIRED, "absolute_path_required")
        if "file_roots" in data:
            roots = [absolute_path(root) for root in data["file_roots"]]
            if None in roots:
                _add(
                    errors,
                    "file_roots",
                    ABSOLUTE_PATH_REQUIRED,
                    "absolute_path_required",
                )
            else:
                cleaned["file_roots"] = list(dict.fromkeys(roots))
        return cleaned

    def _pinned(self, line: str, errors: Errors) -> dict[str, str]:
        try:
            key = parse_host_key(line)
        except ValueError:
            _add(errors, "host_key", INVALID_HOST_KEY, "invalid_host_key")
            return {}
        return {"host_key": key.line, "host_key_fingerprint": key.fingerprint}

    def _credentials(
        self,
        data: dict[str, Any],
        errors: Errors,
        auth_method: str,
        *,
        current: Server | None,
    ) -> dict[str, Any]:
        if auth_method == Server.AuthMethod.KEY:
            changes: dict[str, Any] = {
                "auth_method": auth_method,
                "password_sealed": None,
            }
            if data.get("private_key"):
                changes["private_key_sealed"] = seal_text(
                    data["private_key"], context=vault_contexts.PRIVATE_KEY
                )
                changes["key_passphrase_sealed"] = None
            elif current is None or not current.has_private_key:
                _add(
                    errors, "private_key", PRIVATE_KEY_REQUIRED, "private_key_required"
                )
            if data.get("key_passphrase"):
                changes["key_passphrase_sealed"] = seal_text(
                    data["key_passphrase"], context=vault_contexts.KEY_PASSPHRASE
                )
            return changes

        changes = {
            "auth_method": auth_method,
            "private_key_sealed": None,
            "key_passphrase_sealed": None,
        }
        if data.get("password"):
            changes["password_sealed"] = seal_text(
                data["password"], context=vault_contexts.PASSWORD
            )
        elif current is None or not current.has_password:
            _add(errors, "password", PASSWORD_REQUIRED, "password_required")
        return changes

    def _saved(self, write: Callable[[], Server]) -> Server:
        try:
            with transaction.atomic():
                return write()
        except IntegrityError as exc:
            raise ValidationError(
                {"name": [ErrorDetail(NAME_TAKEN, code="name_taken")]}
            ) from exc


def _output(
    remote: RemoteHost, argv: list[str], *, cwd: str | None = None
) -> str | None:
    try:
        result = remote.run(argv, cwd=cwd)
    except RemoteCommandFailed:
        return None
    lines: list[str] = result.stdout.strip().splitlines()
    if not result.ok or not lines:
        return None
    return lines[-1][:REPORTED_OUTPUT_LIMIT]


def _python_suggestion(
    server: Server, remote: RemoteHost, project_dir: str
) -> dict[str, str] | None:
    others = [
        python
        for python in pythons.candidates(remote, project_dir)
        if python != server.python_path
    ]
    found = pythons.with_dbs(remote, others, project_dir)
    if found is None:
        return None
    return {"python_path": found.python_path, "dbs_version": found.dbs_version}


def _succeeds(
    remote: RemoteHost, argv: list[str], *, cwd: str, env: dict[str, str] | None
) -> bool:
    try:
        ok: bool = remote.run(argv, cwd=cwd, env=env).ok
        return ok
    except RemoteCommandFailed:
        return False


def _exists(remote: RemoteHost, path: str) -> bool:
    try:
        return remote.exists(path)
    except RemoteCommandFailed:
        return False


def _ready(report: dict[str, Any]) -> bool:
    return (
        report["dbs_version"] is not None
        and report["backup_command"] is not False
        and report["env_file"] is not False
        and all(report["roots"].values())
        and report["remote_backup_dir"]
    )


def _settings_env(server: Server) -> dict[str, str] | None:
    if not server.settings_module:
        return None
    return {"DJANGO_SETTINGS_MODULE": server.settings_module}


def _health_report(stdout: str) -> dict[str, Any] | None:
    try:
        report = json.loads(stdout.strip() or "null")
    except ValueError:
        return None
    if not isinstance(report, dict) or report.get("status") not in HEALTH_STATUSES:
        return None
    return report
