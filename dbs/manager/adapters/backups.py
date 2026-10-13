from __future__ import annotations

import shutil
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rest_framework.exceptions import APIException

from dbs.manager.adapters import AdapterError, jobs
from dbs.manager.adapters.local import private_file
from dbs.manager.adapters.problems import problem
from dbs.manager.backups.services import BackupService
from dbs.manager.backups.services.backup_run_service import KEPT_ON_SERVER
from dbs.manager.servers.models import Server

KEPT_ON_SERVER_RESULT = "kept on the server; collected at the next connection"


@dataclass(frozen=True)
class Taken:
    server: str
    ok: bool
    backup: str | None
    size: int | None
    error: str
    activity: dict[str, Any] | None
    kept_on_server: bool = False

    @property
    def result(self) -> str:
        if not self.ok:
            return f"failed: {self.error}"
        return KEPT_ON_SERVER_RESULT if self.kept_on_server else "ok"

    def as_dict(self) -> dict[str, Any]:
        return {
            "server": self.server,
            "ok": self.ok,
            "kept_on_server": self.kept_on_server,
            "backup": self.backup,
            "size": self.size,
            "error": self.error,
            "activity": self.activity,
        }


def take(
    user: Any,
    chosen: Iterable[Server],
    starting: Callable[[Server], None] = lambda server: None,
) -> list[Taken]:
    service = BackupService(user)
    taken = []
    for server in chosen:
        starting(server)
        try:
            entry = jobs.finished(user, service.take(server.pk))
        except APIException as exc:
            taken.append(Taken(server.name, False, None, None, problem(exc), None))
            continue
        detail = entry.data or {}
        ok = jobs.succeeded(entry)
        taken.append(
            Taken(
                server=server.name,
                ok=ok,
                backup=detail.get("backup") if ok else None,
                size=detail.get("size") if ok else None,
                error="" if ok else jobs.failure(entry),
                activity=jobs.described(user, entry),
                kept_on_server=ok and detail.get("outcome") == KEPT_ON_SERVER,
            )
        )
    return taken


def save(user: Any, file_id: Any, target: Path, account_password: str = "") -> Path:
    service = BackupService(user)
    if target.is_dir():
        target = target / service.get(file_id).name
    if target.exists():
        raise AdapterError(f"{target} already exists; nothing was overwritten.")
    fetched = service.download(file_id, account_password=account_password)
    try:
        with private_file(target) as handle:
            if hasattr(fetched.content, "read"):
                shutil.copyfileobj(fetched.content, handle)
            else:
                for chunk in fetched.content:
                    handle.write(chunk)
    except FileExistsError:
        raise AdapterError(
            f"{target} already exists; nothing was overwritten."
        ) from None
    finally:
        fetched.content.close()
    return target
