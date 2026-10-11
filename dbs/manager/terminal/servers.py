from __future__ import annotations

from pathlib import Path
from typing import Any

from rest_framework.exceptions import APIException

from dbs.manager.servers.models import Server
from dbs.manager.servers.serializers import (
    AddedServerSerializer,
    HostKeySerializer,
    ServerCreateSerializer,
    ServerListSerializer,
    ServerSerializer,
    ServerUpdateSerializer,
)
from dbs.manager.servers.serializers.browse import BrowseEntrySerializer
from dbs.manager.servers.services import BrowseService, DiscoveryService, ServerService
from dbs.manager.servers.services.discovery_service import discovered_settings
from dbs.manager.adapters import references, servers
from dbs.manager.terminal import CommandFailed
from dbs.manager.adapters.forms import validated
from dbs.manager.adapters.problems import problem
from dbs.manager.terminal.session import TerminalSession

SETTING_FIELDS = (
    "runtime",
    "compose_service",
    "compose_files",
    "project_dir",
    "python_path",
    "manage_path",
    "settings_module",
    "remote_backup_dir",
    "env_path",
    "file_roots",
)
SHOWN_FIELDS = (
    "id",
    "name",
    "host",
    "port",
    "username",
    "auth_method",
    "host_key_fingerprint",
    "runtime",
    "compose_service",
    "compose_files",
    "project_dir",
    "python_path",
    "manage_path",
    "settings_module",
    "remote_backup_dir",
    "env_path",
    "file_roots",
    "last_check_status",
    "last_check_error",
    "last_checked_at",
)
LIST_COLUMNS = (
    ("NAME", "name"),
    ("HOST", lambda row: f"{row['username']}@{row['host']}:{row['port']}"),
    ("STATUS", "last_check_status"),
    ("CHECKED", "last_checked_at"),
    ("ID", "id"),
)
CHECK_COLUMNS = (
    ("SERVER", "name"),
    ("STATUS", "status"),
    ("DJANGO-DBS", "remote_version"),
    ("PROBLEM", "problem"),
)
BROWSE_COLUMNS = (
    ("KIND", "kind"),
    ("SIZE", "size"),
    ("MODIFIED", "modified"),
    ("NAME", "name"),
)
DEFAULT_PORT = 22


def list_servers(session: TerminalSession) -> int:
    found = ServerService(session.user).list(session.args.search).order_by("name")
    rows = ServerListSerializer(found, many=True).data
    session.out.table(
        rows, LIST_COLUMNS, empty="No servers yet. Add one with: django_dbs server add"
    )
    return 0


def show(session: TerminalSession) -> int:
    server = references.server(session.user, session.args.server)
    session.out.fields(ServerSerializer(server).data, SHOWN_FIELDS)
    return 0


def add(session: TerminalSession) -> int:
    args = session.args
    service = ServerService(session.user)
    port = args.port or DEFAULT_PORT
    host_key = args.host_key or _offered_key(session, service, args.host, port)
    body: dict[str, Any] = {
        "name": args.name,
        "host": args.host,
        "port": port,
        "username": args.username,
        "host_key": host_key,
        **_auth(session),
        **_given_settings(args),
    }
    if args.generate_key:
        body["generate_key"] = True
    if args.backup_passphrase:
        body["backup_passphrase"] = session.secret("Backup passphrase")
    added = service.add(**validated(ServerCreateSerializer, body))
    server = added.server
    _say(session, f"Added {server.name}.")
    if added.public_key:
        _say(session, "Add this line to the server's authorized_keys, then run:")
        _say(session, f"  {added.authorized_keys_hint}")
        _say(session, f"  django_dbs server check {server.name}")
        if session.out.as_json:
            session.out.json(AddedServerSerializer(added).data)
        return 0
    if not args.no_discover:
        server = _discover_and_save(
            session, server, args.project_dir, _given_settings(args)
        )
    rows, results = _checked(session, [server])
    if session.out.as_json:
        session.out.json({**AddedServerSerializer(added).data, "check": results[0]})
    else:
        session.out.table(rows, CHECK_COLUMNS, empty="")
    return 0


def edit(session: TerminalSession) -> int:
    args = session.args
    server = references.server(session.user, args.server)
    body: dict[str, Any] = {
        key: value
        for key, value in {
            "name": args.name,
            "host": args.host,
            "port": args.port,
            "username": args.username,
            **_given_settings(args),
        }.items()
        if value is not None
    }
    body.update(_auth(session, required=False))
    if args.backup_passphrase:
        body["backup_passphrase"] = session.secret("Backup passphrase")
    if not body:
        raise CommandFailed("nothing to change; pass at least one option.")
    changes = validated(ServerUpdateSerializer, body, partial=True)
    service = ServerService(session.user)
    saved = session.guarded(
        lambda password: service.update(server.pk, account_password=password, **changes)
    )
    session.out.say(f"Saved {saved.name}.", ServerSerializer(saved).data)
    return 0


def remove(session: TerminalSession) -> int:
    server = references.server(session.user, session.args.server)
    session.confirm(
        f"Type the server's name ({server.name}) to remove it:", expected=server.name
    )
    ServerService(session.user).delete(server.pk)
    session.out.say(f"Removed {server.name}.", {"removed": str(server.pk)})
    return 0


def check(session: TerminalSession) -> int:
    chosen = references.servers(session.user, session.args.servers, session.args.all)
    return _report_check(session, chosen)


def discover(session: TerminalSession) -> int:
    args = session.args
    server = references.server(session.user, args.server)
    discovery = DiscoveryService(session.user)
    found = session.guarded(
        lambda password: discovery.discover(
            server.pk, project_dir=args.project or None, account_password=password
        )
    )
    if args.save:
        changes = discovered_settings(found, chosen=bool(args.project))
        service = ServerService(session.user)
        if changes:
            session.guarded(
                lambda password: service.update(
                    server.pk, account_password=password, **changes
                )
            )
    if session.out.as_json:
        session.out.json(found)
        return 0
    session.out.fields(
        found,
        (
            "runtime",
            "compose_service",
            "project_dir",
            "python_path",
            "settings_module",
            "env_path",
            "dbs_version",
        ),
    )
    candidates = found.get("candidates", {})
    others = [
        path
        for path in candidates.get("project_dirs", [])
        if path != found["project_dir"]
    ]
    if others:
        print(f"other projects  {', '.join(others)}")
    if args.save:
        print(f"Saved these settings to {server.name}.")
    return 0


def browse(session: TerminalSession) -> int:
    server = references.server(session.user, session.args.server)
    folder = BrowseService(session.user).list(server.pk, session.args.path or None)
    entries = BrowseEntrySerializer(folder.entries, many=True).data
    listing = {
        "path": folder.path,
        "parent": folder.parent,
        "home": folder.home,
        "project": folder.project,
        "truncated": folder.truncated,
        "count": len(entries),
        "results": entries,
    }
    if not session.out.as_json:
        print(folder.path + ("  (a Django project)" if folder.project else ""))
    session.out.table(
        entries, BROWSE_COLUMNS, empty="This folder is empty.", data=listing
    )
    if folder.truncated and not session.out.as_json:
        print("Only the first entries are shown.")
    return 0


def public_key(session: TerminalSession) -> int:
    server = references.server(session.user, session.args.server)
    key = ServerService(session.user).public_key(server.pk)
    session.out.say(key, {"public_key": key})
    return 0


def host_key(session: TerminalSession) -> int:
    args = session.args
    server = references.server(session.user, args.server)
    service = ServerService(session.user)
    offered = args.host_key or _offered_key(session, service, server.host, server.port)
    saved = service.repin(server.pk, offered, session.password())
    session.out.say(
        f"Pinned {saved.host_key_fingerprint} for {saved.name}.",
        ServerSerializer(saved).data,
    )
    return 0


def passphrase(session: TerminalSession) -> int:
    server = references.server(session.user, session.args.server)
    shown = ServerService(session.user).reveal_passphrase(server.pk, session.password())
    session.out.say(shown, {"passphrase": shown})
    return 0


def capture_passphrase(session: TerminalSession) -> int:
    server = references.server(session.user, session.args.server)
    ServerService(session.user).capture_passphrase(server.pk)
    session.out.say(
        f"Read the backup passphrase from {server.name}.", {"captured": True}
    )
    return 0


def import_profiles(session: TerminalSession) -> int:
    from dbs.client.config import load_client_config
    from dbs.exceptions import DBSError

    try:
        config = load_client_config(session.args.file)
    except DBSError as exc:
        raise CommandFailed(str(exc)) from exc
    service = ServerService(session.user)
    failed = 0
    for profile in config.servers.values():
        try:
            server = _imported(session, service, profile)
        except (APIException, CommandFailed) as exc:
            failed += 1
            message = problem(exc) if isinstance(exc, APIException) else str(exc)
            print(f"{profile.name}: not added: {message}")
            continue
        print(f"{profile.name}: added as {server.name}.")
    return 1 if failed else 0


def _imported(session: TerminalSession, service: ServerService, profile: Any) -> Server:
    body: dict[str, Any] = {
        "name": profile.name,
        "host": profile.host,
        "port": profile.port,
        "username": profile.username,
        "host_key": profile.host_key
        or _offered_key(session, service, profile.host, profile.port),
        "python_path": profile.python,
        "manage_path": profile.manage,
    }
    if profile.remote_dir.startswith("/"):
        body["remote_backup_dir"] = profile.remote_dir
    if profile.project_dir:
        body["project_dir"] = profile.project_dir
    if profile.django_settings_module:
        body["settings_module"] = profile.django_settings_module
    if profile.key_filename:
        body.update(
            auth_method=Server.AuthMethod.KEY,
            private_key=_read_key(profile.key_filename),
        )
        if profile.key_passphrase:
            body["key_passphrase"] = profile.key_passphrase
    elif profile.password:
        body.update(auth_method=Server.AuthMethod.PASSWORD, password=profile.password)
    else:
        raise CommandFailed("it names no key file or password the manager can keep.")
    if profile.passphrase:
        body["backup_passphrase"] = profile.passphrase
    return service.add(**validated(ServerCreateSerializer, body)).server


def _offered_key(
    session: TerminalSession, service: ServerService, host: str, port: int
) -> str:
    offered = service.fingerprint(host, port)
    shown = HostKeySerializer(offered).data
    if not session.out.as_json:
        print(f"{host}:{port} offers {shown['key_type']} {shown['fingerprint']}")
    session.confirm("Is this the server's key? [y/N]")
    return shown["line"]


def _auth(session: TerminalSession, required: bool = True) -> dict[str, Any]:
    args = session.args
    if getattr(args, "generate_key", False):
        return {}
    if args.key_file:
        auth = {
            "auth_method": Server.AuthMethod.KEY,
            "private_key": _read_key(args.key_file),
        }
        if args.key_passphrase:
            auth["key_passphrase"] = session.secret("Key passphrase")
        return auth
    if args.ssh_password or args.ssh_password_stdin:
        if args.ssh_password_stdin and args.password_stdin:
            raise CommandFailed("stdin can carry one secret; drop --password-stdin.")
        return {
            "auth_method": Server.AuthMethod.PASSWORD,
            "password": session.secret(
                "SSH password", args.ssh_password_stdin, "--ssh-password-stdin"
            ),
        }
    if required:
        raise CommandFailed(
            "choose how to sign in: --key-file, --ssh-password or --generate-key."
        )
    return {}


def _read_key(path: str) -> str:
    try:
        return Path(path).expanduser().read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise CommandFailed(f"could not read {path}: {exc}") from exc


def _given_settings(args: Any) -> dict[str, Any]:
    return {
        field: getattr(args, field)
        for field in SETTING_FIELDS
        if getattr(args, field, None) is not None
    }


def _discover_and_save(
    session: TerminalSession, server: Server, project: str | None, given: dict[str, Any]
) -> Server:
    settled = servers.settle(session.user, server, project, given)
    if settled.error:
        _say(session, f"Could not look around {server.name}: {settled.error}")
    elif settled.found and settled.found["project_dir"]:
        found = settled.found
        service = found.get("compose_service")
        where = f" (Docker Compose service {service})" if service else ""
        _say(session, f"Found the project in {found['project_dir']}{where}.")
    else:
        _say(
            session,
            "Found no Django project; set one with: django_dbs server edit --project-dir",
        )
    return settled.server


def _report_check(session: TerminalSession, chosen: list[Server]) -> int:
    rows, results = _checked(session, chosen)
    session.out.table(rows, CHECK_COLUMNS, empty="", data=results)
    return 0 if all(row["status"] == Server.CheckStatus.OK for row in rows) else 1


def _checked(
    session: TerminalSession, chosen: list[Server]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    done = servers.checked(session.user, chosen)
    rows = [
        {
            "name": item.name,
            "status": item.status,
            "remote_version": item.remote_version,
            "problem": item.problem,
        }
        for item in done
    ]
    return rows, [item.result for item in done]


def _say(session: TerminalSession, message: str) -> None:
    if not session.out.as_json:
        print(message)
