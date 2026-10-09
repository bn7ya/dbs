from __future__ import annotations

import secrets
import threading
import time
from typing import Any

from django.contrib.auth import login
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction

from dbs import audit, leases
from dbs.manager import paths
from dbs.manager.accounts.exceptions import (
    PasswordInvalid,
    SetupDone,
    SetupTokenInvalid,
)
from dbs.manager.accounts.repositories import UserRepository
from dbs.manager.conf import LEASE_SECONDS, SETUP_LEASE, data_dir
from dbs.manager.middleware import current_ip

SETUP_ACTION = "account.setup"
LEASE_WAIT_SECONDS = 5.0
LEASE_POLL_SECONDS = 0.05


def token_path():
    return paths.setup_token_path(data_dir())


def write_token():
    token = secrets.token_urlsafe(32)
    paths.write_private(token_path(), token)
    return token


def token_matches(token: str) -> bool:
    try:
        stored = token_path().read_text(encoding="utf-8").strip()
    except OSError:
        return False
    return bool(stored) and secrets.compare_digest(stored, token or "")


def remove_token() -> None:
    try:
        token_path().unlink()
    except FileNotFoundError:
        pass


class SetupService:
    def __init__(self) -> None:
        self.users = UserRepository()

    def needed(self) -> bool:
        return not self.users.any_exist()

    def complete(
        self, request: Any, *, token: str, username: str, password: str
    ) -> Any:
        owner = f"{leases.process_owner()}:{threading.get_ident()}"
        self._take(owner)
        try:
            with transaction.atomic():
                user = self._create(token, username, password)
        finally:
            leases.release(SETUP_LEASE, owner)
        login(request, user)
        remove_token()
        return user

    def _take(self, owner: str) -> None:
        deadline = time.monotonic() + LEASE_WAIT_SECONDS
        while not leases.acquire(SETUP_LEASE, owner, LEASE_SECONDS):
            if time.monotonic() > deadline:
                raise SetupDone()
            time.sleep(LEASE_POLL_SECONDS)

    def _create(self, token: str, username: str, password: str) -> Any:
        if self.users.any_exist():
            raise SetupDone()
        if not token_matches(token):
            raise SetupTokenInvalid()
        try:
            validate_password(password, user=self.users.unsaved(username))
        except DjangoValidationError as exc:
            raise PasswordInvalid(" ".join(exc.messages)) from exc
        user = self.users.create_superuser(username=username, password=password)
        audit.record(
            SETUP_ACTION, actor=user, target=username, remote_addr=current_ip() or ""
        )
        return user
