from __future__ import annotations

import logging

from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.dispatch import receiver

from .features import client_address
from .sessions import clear_reauthentication

logger = logging.getLogger("dbs")


@receiver(user_login_failed)
def record_login_failure(sender, credentials=None, request=None, **kwargs):
    if request is None:
        return
    from .. import audit

    try:
        audit.safe_record(
            "auth.failed",
            target=str((credentials or {}).get("username", "")),
            remote_addr=client_address(request),
            status=audit.FAILED,
        )
    except Exception:
        logger.exception("DBS could not record a failed sign-in")


@receiver(user_logged_in)
def reset_session_flags(sender, request=None, user=None, **kwargs):
    if request is not None:
        clear_reauthentication(request)
