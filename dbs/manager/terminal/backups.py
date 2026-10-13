from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from django.core.files.uploadedfile import UploadedFile

from dbs.manager.backups.serializers import (
    BackupFileSerializer,
    RestoreSerializer,
)
from dbs.manager.backups.services import BackupService
from dbs.manager.servers.services import ServerService
from dbs.manager.adapters import backups, jobs, references
from dbs.manager.terminal import CommandFailed
from dbs.manager.adapters.forms import validated
from dbs.manager.terminal.progress import reported
from dbs.manager.terminal.session import TerminalSession

LIST_COLUMNS = (
    ("NAME", "name"),
    ("SERVER", "server_name"),
    ("KIND", "kind"),
    ("SIZE", "size"),
    ("VALIDATION", "validation"),
    ("TAKEN", "created_at"),
    ("ID", "id"),
)
TAKE_COLUMNS = (
    ("SERVER", "server"),
    ("RESULT", "result"),
    ("BACKUP", "backup"),
    ("SIZE", "size"),
)


def list_backups(session: TerminalSession) -> int:
    service = BackupService(session.user)
    if session.args.server:
        chosen = [references.server(session.user, session.args.server)]
    else:
        chosen = list(ServerService(session.user).list().order_by("name"))
    rows = [
        row
        for server in chosen
        for row in BackupFileSerializer(service.list(server.pk), many=True).data
    ]
    session.out.table(rows, LIST_COLUMNS, empty="No backups yet.")
    return 0


def take(session: TerminalSession) -> int:
    chosen = references.servers(session.user, session.args.servers, session.args.all)
    with reported(session):
        taken = backups.take(
            session.user, chosen, starting=lambda server: _starting(session, server)
        )
    rows = [
        {
            "server": item.server,
            "result": item.result,
            "backup": item.backup,
            "size": item.size,
        }
        for item in taken
    ]
    session.out.table(
        rows, TAKE_COLUMNS, empty="", data=[item.as_dict() for item in taken]
    )
    return 0 if all(item.ok for item in taken) else 1


def _starting(session: TerminalSession, server: Any) -> None:
    if not session.out.as_json:
        print(f"Backing up {server.name}...", flush=True)


def verify(session: TerminalSession) -> int:
    file_id = references.identifier(session.args.backup, "backup")
    entry = jobs.finished(session.user, BackupService(session.user).verify(file_id))
    return session.outcome(entry, "Verified the backup.")


def restore(session: TerminalSession) -> int:
    args = session.args
    file_id = references.identifier(args.backup, "backup")
    service = BackupService(session.user)
    file = service.get(file_id)
    target = references.server(session.user, args.to) if args.to else file.server
    body: dict[str, Any] = {"mode": args.mode, "rehearse": not args.real}
    if target.pk != file.server_id:
        body["target_server"] = target.pk
    if args.real:
        body["server_name"] = args.confirm_name or _typed_name(session, target.name)
        body["account_password"] = session.password()
    with reported(session):
        job = service.restore(file_id, **validated(RestoreSerializer, body))
    entry = jobs.finished(session.user, job)
    done = "Restored" if args.real else "Rehearsed restoring"
    return session.outcome(entry, f"{done} {file.name} onto {target.name}.")


def download(session: TerminalSession) -> int:
    file_id = references.identifier(session.args.backup, "backup")
    target = Path(session.args.output or BackupService(session.user).get(file_id).name)
    saved = session.guarded(
        lambda password: backups.save(
            session.user, file_id, target, account_password=password
        )
    )
    size = saved.stat().st_size
    session.out.say(
        f"Saved {saved} ({size} bytes).", {"path": str(saved.resolve()), "size": size}
    )
    return 0


def upload(session: TerminalSession) -> int:
    server = references.server(session.user, session.args.server)
    local = local_file(session.args.file)
    stored = BackupService(session.user).upload(server.pk, local)
    session.out.say(
        f"Kept {stored.name} for {server.name}.", BackupFileSerializer(stored).data
    )
    return 0


def delete(session: TerminalSession) -> int:
    file_id = references.identifier(session.args.backup, "backup")
    service = BackupService(session.user)
    session.guarded(lambda password: service.delete(file_id, account_password=password))
    session.out.say(
        f"Deleted it. Bring it back with: django_dbs backup undo-delete {file_id}",
        {"deleted": str(file_id)},
    )
    return 0


def undo_delete(session: TerminalSession) -> int:
    file_id = references.identifier(session.args.backup, "backup")
    file = BackupService(session.user).undo_delete(file_id)
    session.out.say(f"Brought back {file.name}.", BackupFileSerializer(file).data)
    return 0


def local_file(path: str) -> UploadedFile:
    try:
        handle = open(path, "rb")
    except OSError as exc:
        raise CommandFailed(f"could not open {path}: {exc.strerror}") from exc
    return UploadedFile(
        file=handle, name=os.path.basename(path), size=os.fstat(handle.fileno()).st_size
    )


def _typed_name(session: TerminalSession, name: str) -> str:
    session.confirm(
        f"Type the target server's name ({name}) to go ahead:", expected=name
    )
    return name
