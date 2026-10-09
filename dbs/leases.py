from __future__ import annotations

import os
import socket
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone


def process_owner():
    return f"{socket.gethostname()}:{os.getpid()}"


def acquire(name, owner, ttl_seconds):
    from .models import Lease

    now = timezone.now()
    try:
        with transaction.atomic():
            Lease.objects.get_or_create(
                name=name, defaults={"owner": "", "expires_at": now}
            )
    except IntegrityError:
        pass
    taken = (
        Lease.objects.filter(name=name)
        .filter(Q(expires_at__lte=now) | Q(owner=owner))
        .update(
            owner=owner,
            expires_at=now + timedelta(seconds=ttl_seconds),
            renewed_at=now,
        )
    )
    return taken == 1


def release(name, owner):
    from .models import Lease

    Lease.objects.filter(name=name, owner=owner).update(
        owner="", expires_at=timezone.now()
    )


def holder(name):
    from .models import Lease

    return Lease.objects.filter(
        name=name, expires_at__gt=timezone.now()
    ).exclude(owner="").first()


def last_renewed(name):
    from .models import Lease

    lease = Lease.objects.filter(name=name).first()
    return None if lease is None else lease.renewed_at
