from __future__ import annotations

import shutil
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rest_framework.exceptions import APIException

from dbs import audit
from dbs.manager.adapters import AdapterError, jobs
from dbs.manager.adapters.local import private_file
from dbs.manager.adapters.problems import problem
from dbs.manager.applications.models import Application
from dbs.manager.backups.services import BackupService
from dbs.manager.backups.services.backup_run_service import KEPT_ON_SERVER

KEPT_ON_SERVER_RESULT = "kept on the server; collected at the next connection"


@dataclass(frozen=True)
class Taken:
    application: str
    ok: bool
    backup: str | None
    size: int | None
    error: str
    activity: dict[str, Any] | None
    kept_on_server: bool = False
    started: bool = False

    @property
    def result(self) -> str:
        if not self.ok:
            return f"failed: {self.error}"
        if self.started:
            return "started"
        return KEPT_ON_SERVER_RESULT if self.kept_on_server else "ok"

    def as_dict(self) -> dict[str, Any]:
        return {
            "application": self.application,
            "ok": self.ok,
            "started": self.started,
            "kept_on_server": self.kept_on_server,
            "backup": self.backup,
            "size": self.size,
            "error": self.error,
            "activity": self.activity,
        }


def take(
    user: Any,
    chosen: Iterable[Application],
    starting: Callable[[Application], None] = lambda application: None,
) -> list[Taken]:
    service = BackupService(user)
    taken = []
    for application in chosen:
        starting(application)
        try:
            entry = jobs.finished(user, service.take(application.pk))
        except APIException as exc:
            taken.append(
                Taken(application.name, False, None, None, problem(exc), None)
            )
            continue
        detail = entry.data or {}
        started = entry.status in (audit.QUEUED, audit.RUNNING)
        ok = started or jobs.succeeded(entry)
        taken.append(
            Taken(
                application=application.name,
                ok=ok,
                backup=detail.get("backup") if ok else None,
                size=detail.get("size") if ok else None,
                error="" if ok else jobs.failure(entry),
                activity=jobs.described(user, entry),
                kept_on_server=ok and detail.get("outcome") == KEPT_ON_SERVER,
                started=started,
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
