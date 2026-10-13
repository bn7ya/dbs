from __future__ import annotations

import logging
import os
import socket
import threading
import uuid
from datetime import timedelta

from django.db import DatabaseError, IntegrityError, connections, transaction
from django.db.models import Q
from django.utils import timezone

logger = logging.getLogger("dbs")

OWNER_MAX = 128


def process_owner():
    return f"{socket.gethostname()}:{os.getpid()}"


def unique_owner():
    return f"{uuid.uuid4().hex[:16]}:{threading.get_ident()}:{process_owner()}"[:OWNER_MAX]


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


def renew(name, owner, ttl_seconds):
    from .models import Lease

    now = timezone.now()
    renewed = Lease.objects.filter(name=name, owner=owner).update(
        expires_at=now + timedelta(seconds=ttl_seconds), renewed_at=now
    )
    return renewed == 1


def release(name, owner):
    from .models import Lease

    Lease.objects.filter(name=name, owner=owner).update(
        owner="", expires_at=timezone.now()
    )


def drop(name, owner):
    from .models import Lease

    Lease.objects.filter(name=name, owner=owner).delete()


def holder(name):
    from .models import Lease

    return Lease.objects.filter(
        name=name, expires_at__gt=timezone.now()
    ).exclude(owner="").first()


def last_renewed(name):
    from .models import Lease

    lease = Lease.objects.filter(name=name).first()
    return None if lease is None else lease.renewed_at


class Heartbeat:
    def __init__(self, names, owner, ttl_seconds, every_seconds):
        self.names = list(names)
        self.owner = owner
        self.ttl_seconds = ttl_seconds
        self.every_seconds = every_seconds
        self.lost = threading.Event()
        self._stop = threading.Event()
        self._thread = None

    def __enter__(self):
        self._thread = threading.Thread(target=self._beat, name="dbs-heartbeat", daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc_info):
        self._stop.set()
        self._thread.join()
        return False

    def beat(self):
        for name in self.names:
            try:
                renewed = renew(name, self.owner, self.ttl_seconds)
            except DatabaseError as exc:
                logger.warning("could not renew the %s lease: %s", name, exc)
                continue
            if not renewed:
                self.lost.set()
                logger.warning("the %s lease is no longer held by this process", name)

    def _beat(self):
        try:
            while not self._stop.wait(self.every_seconds):
                self.beat()
        finally:
            connections.close_all()
