from __future__ import annotations

from pathlib import Path

from dbs.manager.files.serializers import FileEntrySerializer
from dbs.manager.files.services import FileService
from dbs.manager.terminal import CommandFailed, references
from dbs.manager.terminal.backups import local_file
from dbs.manager.terminal.session import TerminalSession

LIST_COLUMNS = (
    ("KIND", "kind"),
    ("MODE", "mode"),
    ("SIZE", "size"),
    ("MODIFIED", "modified"),
    ("NAME", "name"),
)


def list_folder(session: TerminalSession) -> int:
    server = references.server(session.user, session.args.server)
    folder = FileService(session.user).list(server.pk, session.args.path or None)
    entries = FileEntrySerializer(folder.entries, many=True).data
    listing = {
        "path": folder.path,
        "parent": folder.parent,
        "root": folder.root,
        "roots": folder.roots,
        "count": len(entries),
        "results": entries,
    }
    if not session.out.as_json:
        print(folder.path)
    session.out.table(
        entries, LIST_COLUMNS, empty="This folder is empty.", data=listing
    )
    return 0


def download(session: TerminalSession) -> int:
    server = references.server(session.user, session.args.server)
    fetched = FileService(session.user).download(server.pk, session.args.path)
    target = Path(session.args.output or fetched.name)
    if target.is_dir():
        target = target / fetched.name
    written = 0
    try:
        with target.open("xb") as handle:
            for chunk in fetched.content:
                handle.write(chunk)
                written += len(chunk)
    except FileExistsError:
        raise CommandFailed(
            f"{target} already exists; nothing was overwritten."
        ) from None
    finally:
        fetched.content.close()
    session.out.say(
        f"Saved {target} ({written} bytes).",
        {"path": str(target.resolve()), "size": written},
    )
    return 0


def upload(session: TerminalSession) -> int:
    server = references.server(session.user, session.args.server)
    created = FileService(session.user).upload(
        server.pk, session.args.folder, local_file(session.args.file)
    )
    session.out.say(f"Uploaded {created.path}.", FileEntrySerializer(created).data)
    return 0


def mkdir(session: TerminalSession) -> int:
    server = references.server(session.user, session.args.server)
    created = FileService(session.user).create_folder(
        server.pk, session.args.folder, session.args.name
    )
    session.out.say(f"Made {created.path}.", FileEntrySerializer(created).data)
    return 0


def delete(session: TerminalSession) -> int:
    server = references.server(session.user, session.args.server)
    path = session.args.path
    session.confirm(f"Delete {path} on {server.name}? [y/N]")
    FileService(session.user).delete(server.pk, path)
    session.out.say(f"Deleted {path}.", {"deleted": path})
    return 0
