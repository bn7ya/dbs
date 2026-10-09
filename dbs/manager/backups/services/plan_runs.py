from __future__ import annotations

from typing import Any

from dbs.manager.backups.models import BackupPlan
from dbs.models import AuditEvent


def run_detail(plan: BackupPlan) -> dict[str, str]:
    return {"plan": str(plan.pk)}


def last_run(entry: AuditEvent) -> dict[str, Any]:
    return {
        "last_run_at": entry.finished_at,
        "last_status": entry.status,
        "last_error_code": entry.error_code,
    }
