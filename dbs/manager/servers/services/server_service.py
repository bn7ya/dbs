from __future__ import annotations

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
from dbs.manager.servers import keys
from dbs.manager.servers.exceptions import (
    HostKeyChanged,
    NoPrivateKey,
    RemoteCommandFailed,
    ServerHasApplications,
    ServersDiffer,
    SSHAuthFailed,
    SSHUnreachable,
)
from dbs.manager.servers.gateways import (
    ENGINES,
    HostKey,
    RemoteHost,
    fetch_host_key,
    parse_host_key,
)
from dbs.manager.servers.models import Server
from dbs.manager.servers.repositories import ServerRepository
from dbs.manager.servers.services import vault_contexts
from dbs.manager.servers.services.connection_service import ServerConnectionService
from dbs.manager.vault import seal_text
from dbs.manager.permissions import Capability, requires

if TYPE_CHECKING:
    from django.contrib.auth.models import AnonymousUser, User

PLAIN_FIELDS = ("name", "host", "port", "username")
UNGUARDED_FIELDS = frozenset({"name"})
SETUP_WINDOW = timedelta(hours=1)
CONNECTION_ERRORS = (HostKeyChanged, SSHAuthFailed, SSHUnreachable)
REPORTED_OUTPUT_LIMIT = 200
ENGINE_VERSIONS = {
    "docker": ["docker", "version", "--format", "{{.Server.Version}}"],
    "podman": ["podman", "version", "--format", "{{.Version}}"],
}
COMPOSE_VERSIONS = {
    "docker": ["docker", "compose", "version", "--short"],
    "podman": ["podman", "compose", "version", "--short"],
}
PERMISSION_DENIED = "permission denied"
NOT_FOUND = 127
ABSENT = {"installed": False, "usable": False, "version": None, "compose": None, "error": ""}

INVALID_HOST_KEY = "Paste the host key as one line, for example 'ssh-ed25519 AAAA...'."
NAME_TAKEN = "Another server already has this name."
PRIVATE_KEY_REQUIRED = "Paste the private key this server accepts."
PASSWORD_REQUIRED = "Enter the password this server accepts."
ACCOUNT_PASSWORD_REQUIRED = "Enter your own password to change this."
DELETE_PASSWORD_REQUIRED = "Enter your own password to delete a server."
MERGE_PASSWORD_REQUIRED = "Enter your own password to join two servers."

Errors = dict[str, list[ErrorDetail]]


class Action:
    CREATE = "server.create"
    UPDATE = "server.update"
    DELETE = "server.delete"
    CHECK = "server.check"
    REPIN = "server.repin"
    FINGERPRINT = "server.fingerprint"
    KEYPAIR = "server.keypair"
    MERGE = "server.merge"


def _add(errors: Errors, field: str, message: str, code: str) -> None:
    errors.setdefault(field, []).append(ErrorDetail(message, code=code))


def address(host: str, port: int) -> str:
    return f"[{host}]:{port}" if ":" in host else f"{host}:{port}"


def changed_fields(instance: Any, changes: dict[str, Any]) -> list[str]:
    names = set()
    for column, value in changes.items():
        if column.endswith("_sealed"):
            if value is not None or getattr(instance, column) is not None:
                names.add(column[: -len("_sealed")])
        elif getattr(instance, column) != value:
            names.add(column)
    return sorted(names)


def require_account_password(account_password: str, message: str) -> None:
    if not account_password:
        raise ValidationError(
            {"account_password": [ErrorDetail(message, code="required")]}
        )


@dataclass(frozen=True)
class AddedServer:
    server: Server
    public_key: str | None = None
    authorized_keys_hint: str | None = None


class ServerService:
    def __init__(self, user: User | AnonymousUser | None) -> None:
        self.user: User | AnonymousUser | None = user
        self.servers = ServerRepository()
        self.connections = ServerConnectionService(user)
        self.activity = ActivityService(user)

    def list(self, search: str | None = None) -> QuerySet[Server]:
        return self.servers.search((search or "").strip() or None)

    def get(self, server_id: UUID) -> Server:
        server = self.servers.find(server_id)
        if server is None:
            raise NotFound()
        return server

    @requires(Capability.SERVERS_MANAGE)
    def fingerprint(self, host: str, port: int) -> HostKey:
        with self.activity.track(
            Action.FINGERPRINT, target=address(host, port)
        ) as entry:
            key = fetch_host_key(host, port)
            entry.detail = {"fingerprint": key.fingerprint}
            return key

    @requires(Capability.SERVERS_MANAGE)
    def add(self, **data: Any) -> AddedServer:
        if not data.pop("generate_key", False):
            return AddedServer(server=self.create(**data))
        server, public_key = self.create_with_key(**data)
        return AddedServer(
            server=server,
            public_key=public_key,
            authorized_keys_hint=keys.authorized_keys_hint(public_key, server.username),
        )

    @requires(Capability.SERVERS_MANAGE)
    def create(self, **data: Any) -> Server:
        data.pop("generate_key", None)
        errors: Errors = {}
        fields = {name: data[name] for name in PLAIN_FIELDS if name in data}
        fields |= self._pinned(data["host_key"], errors)
        fields |= self._credentials(data, errors, data["auth_method"], current=None)
        if self.servers.name_in_use(data["name"]):
            _add(errors, "name", NAME_TAKEN, "name_taken")
        if errors:
            raise ValidationError(errors)
        with transaction.atomic():
            server = self._saved(
                lambda: self.servers.create(
                    created_by=cast("User | None", self.user), **fields
                )
            )
            self.activity.record(Action.CREATE, subject=server, target=server.name)
        return server

    @requires(Capability.SERVERS_MANAGE)
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
                subject=server,
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

    @requires(Capability.SERVERS_MANAGE)
    def update(
        self, server_id: UUID, account_password: str = "", **data: Any
    ) -> Server:
        server = self.get(server_id)
        errors: Errors = {}
        changes = {name: data[name] for name in PLAIN_FIELDS if name in data}
        changes |= self._credentials(
            data, errors, data.get("auth_method", server.auth_method), current=server
        )
        if "name" in data and self.servers.name_in_use(
            data["name"], excluding=server.pk
        ):
            _add(errors, "name", NAME_TAKEN, "name_taken")
        if errors:
            raise ValidationError(errors)
        changed = changed_fields(server, changes)
        guarded = not UNGUARDED_FIELDS.issuperset(changed) and not self.in_setup(server)
        if guarded:
            require_account_password(account_password, ACCOUNT_PASSWORD_REQUIRED)
        name = changes.get("name", server.name)
        with self.activity.track(Action.UPDATE, subject=server, target=name) as entry:
            entry.detail = {"fields": changed}
            if guarded or account_password:
                AccountService(self.user).confirm_password(account_password)
            return self._saved(lambda: self.servers.update(server, **changes))

    def in_setup(self, server: Server) -> bool:
        return (
            self.user is not None
            and self.user.is_authenticated
            and server.created_by_id == self.user.pk
            and server.created_at > timezone.now() - SETUP_WINDOW
        )

    @requires(Capability.SERVERS_MANAGE)
    def delete(self, server_id: UUID, account_password: str = "") -> None:
        from dbs.manager.applications.repositories import ApplicationRepository

        server = self.get(server_id)
        require_account_password(account_password, DELETE_PASSWORD_REQUIRED)
        if ApplicationRepository().on_server(server.pk).exists():
            raise ServerHasApplications()
        with self.activity.track(Action.DELETE, subject=server, target=server.name):
            AccountService(self.user).confirm_password(account_password)
            self.servers.soft_delete(server)

    @requires(Capability.SERVERS_MANAGE)
    def merge(self, server_id: UUID, into: UUID, account_password: str = "") -> Server:
        from dbs.manager.applications.repositories import ApplicationRepository

        source, target = self.get(server_id), self.get(into)
        require_account_password(account_password, MERGE_PASSWORD_REQUIRED)
        if source.pk == target.pk or (
            source.host,
            source.port,
            source.username,
            source.host_key,
        ) != (target.host, target.port, target.username, target.host_key):
            raise ServersDiffer()
        with self.activity.track(
            Action.MERGE, subject=target, target=target.name
        ) as entry:
            AccountService(self.user).confirm_password(account_password)
            with transaction.atomic():
                moved = ApplicationRepository().on_server(source.pk).update(
                    server=target
                )
                self.servers.soft_delete(source)
            entry.detail = {"merged": source.name, "applications": moved}
        return target

    @requires(Capability.SERVERS_MANAGE)
    def repin(self, server_id: UUID, host_key: str, password: str) -> Server:
        server = self.get(server_id)
        with self.activity.track(
            Action.REPIN, subject=server, target=server.name
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

    @requires(Capability.SERVERS_CHECK)
    def check(self, server_id: UUID) -> Server:
        server = self.get(server_id)
        with self.activity.track(
            Action.CHECK, subject=server, target=server.name
        ) as entry:
            try:
                with self.connections.open(server) as remote:
                    report = inspect_host(remote)
            except CONNECTION_ERRORS as exc:
                self._record(
                    server, Server.CheckStatus.FAILED, error_code_of(exc), {}, server.engines
                )
                entry.detail = {"status": Server.CheckStatus.FAILED}
                raise
            status = (
                Server.CheckStatus.OK if report["system"] else Server.CheckStatus.PROBLEM
            )
            entry.detail = {"status": status}
            return self._record(
                server,
                status,
                "",
                report,
                report["engines"],
                timeout_on_host=report["timeout"],
            )

    def _record(
        self,
        server: Server,
        status: str,
        error: str,
        report: dict[str, Any],
        engines: dict[str, Any],
        **extra: Any,
    ) -> Server:
        return self.servers.update(
            server,
            last_check_status=status,
            last_check_error=error,
            last_check_report=report,
            last_checked_at=timezone.now(),
            engines=engines,
            **extra,
        )

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
        if "auth_method" not in data and not any(
            name in data for name in ("private_key", "key_passphrase", "password")
        ) and current is not None:
            return {}
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


def inspect_host(remote: RemoteHost) -> dict[str, Any]:
    return {
        "system": output_of(remote, ["uname", "-sr"]),
        "engines": {engine: engine_report(remote, engine) for engine in ENGINES},
        "timeout": remote.has_timeout(),
    }


def engine_report(remote: RemoteHost, engine: str) -> dict[str, Any]:
    try:
        found = remote.run(ENGINE_VERSIONS[engine])
    except RemoteCommandFailed:
        return dict(ABSENT)
    if found.exit_status == NOT_FOUND:
        return dict(ABSENT)
    if not found.ok:
        message = last_line(found)
        denied = PERMISSION_DENIED in message.lower()
        return {
            "installed": True,
            "usable": False,
            "version": None,
            "compose": None,
            "error": "engine_permission_denied" if denied else message,
        }
    compose = output_of(remote, COMPOSE_VERSIONS[engine])
    return {
        "installed": True,
        "usable": True,
        "version": (found.stdout.strip().splitlines() or [""])[-1][:REPORTED_OUTPUT_LIMIT],
        "compose": compose,
        "error": "",
    }


def output_of(
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


def last_line(result: Any) -> str:
    lines = (result.stderr or result.stdout).strip().splitlines()
    return lines[-1][:REPORTED_OUTPUT_LIMIT] if lines else ""
