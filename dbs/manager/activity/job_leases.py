from __future__ import annotations

from django.conf import settings
from django.utils import timezone

from dbs import leases
from dbs.manager.processes import abandoned
from dbs.models import Lease

PREFIX = "dbs.manager.job:"


def _name(activity_id: int) -> str:
    return f"{PREFIX}{activity_id}"


def hold(activity_id: int) -> None:
    leases.acquire(
        _name(activity_id), leases.process_owner(), settings.BACKUP_TASK_TIME_LIMIT
    )


def let_go(activity_id: int) -> None:
    Lease.objects.filter(name=_name(activity_id)).delete()


def live() -> list[int]:
    held = Lease.objects.filter(
        name__startswith=PREFIX, expires_at__gt=timezone.now()
    ).exclude(owner="")
    return [
        int(lease.name.removeprefix(PREFIX))
        for lease in held
        if not abandoned(lease.owner)
    ]
