from __future__ import annotations

import base64
import secrets
from collections.abc import Sequence
from contextlib import ExitStack
from typing import Any
from uuid import UUID

from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework.exceptions import ErrorDetail, ValidationError

from dbs import audit
from dbs.exceptions import DBSError
from dbs.manager.accounts.services import AccountService
from dbs.manager.activity.services import ActivityService
from dbs.manager.applications.services import ApplicationService
from dbs.manager.permissions import (
    Capability,
    Role,
    RoleRequired,
    allows,
    requires,
    role_of,
)
from dbs.manager.servers.exceptions import RemoteCommandFailed
from dbs.manager.servers.gateways import ContainerTarget, build_script
from dbs.manager.servers.services import ServerConnectionService, ServerService
from dbs.manager.servers.services.connection_service import container_of
from dbs.manager.shell.exceptions import (
    TerminalClosed,
    TerminalNeedsAccount,
    TerminalNotFound,
    TerminalOff,
)
from dbs.manager.shell.sessions import (
    SHELLS,
    UNPOLLED_SECONDS,
    Owner,
    Place,
    Reason,
    ShellSession,
)

OPEN = "shell.session"
SERVER = "server"
APPLICATION = "application"
MODES = (SERVER, APPLICATION)
ADMINS = "admins"
MASTER = "master"
OFF = "off"
POLICIES = (ADMINS, MASTER, OFF)
LONG_POLL = 15.0
INPUT_MAX = 64 * 1024
HOST_SHELL = 'exec "${SHELL:-/bin/sh}" -l'
CONTAINER_SHELL = "if command -v bash >/dev/null 2>&1; then exec bash -l; fi; exec sh -l"
PASSWORD_REQUIRED = "Enter your own password to open a terminal."
INPUT_TOO_LARGE = "Send at most 64 KiB of keystrokes at a time."
PLACE_REQUIRED = "Choose the server or the application to open."


def terminal_policy() -> str:
    chosen = str(getattr(settings, "DBS_MANAGER_TERMINAL", ADMINS)).strip().lower()
    return chosen if chosen in POLICIES else OFF


def terminal_command(target: ContainerTarget, command: Sequence[str]) -> list[str]:
    workdir = ["-w", target.workdir] if target.workdir else []
    if target.in_compose:
        return target.argv("exec", *workdir, target.service, *command)
    return [target.engine, "exec", "-it", *workdir, target.container, *command]


class ShellService:
    def __init__(self, user: Any, session_key: str = "") -> None:
        self.user = user
        self.session_key = session_key or ""

    @requires(Capability.SHELL_OPEN)
    def open(
        self,
        *,
        mode: str,
        server: UUID | None = None,
        application: UUID | None = None,
        password: str = "",
        cols: int = 80,
        rows: int = 24,
    ) -> ShellSession:
        role = self._allowed()
        if not password:
            raise ValidationError(
                {"password": [ErrorDetail(PASSWORD_REQUIRED, code="required")]}
            )
        AccountService(self.user).confirm_password(password)
        subject, place, command = self._place(mode, server, application)
        started = {
            "mode": place.mode,
            "server": place.server_id,
            "application": place.application_id,
            "container": place.container,
            "cols": cols,
            "rows": rows,
        }
        with SHELLS.reserve(self.user.pk):
            connection = ExitStack()
            try:
                remote = connection.enter_context(
                    ServerConnectionService(self.user).open(subject)
                )
                channel = remote.session.open_terminal(command, cols=cols, rows=rows)
            except DBSError as exc:
                connection.close()
                raise RemoteCommandFailed(output=str(exc)[-500:]) from exc
            except BaseException:
                connection.close()
                raise
            entry = ActivityService(self.user).record(
                OPEN,
                subject=subject,
                target=place.label,
                detail=started,
                status=audit.RUNNING,
            )
            session = ShellSession(
                identifier=secrets.token_urlsafe(24),
                owner=Owner(self.user.pk, self.session_key, self.user.password, role),
                place=place,
                cols=cols,
                rows=rows,
                connection=connection,
                channel=channel,
                activity_id=entry.pk,
                started=started,
            )
            SHELLS.add(session)
            session.start()
        return session

    def list(self) -> list[ShellSession]:
        if not self._signed_in():
            return []
        kept = []
        for session in SHELLS.owned_by(self.user.pk):
            if self._still_allowed(session):
                kept.append(session)
            else:
                finish(session, Reason.REVOKED)
        return kept

    def get(self, identifier: str) -> ShellSession:
        session = SHELLS.find(identifier)
        if (
            session is None
            or session.finished
            or not self._signed_in()
            or session.owner.user_id != self.user.pk
        ):
            raise TerminalNotFound()
        if not self._still_allowed(session):
            finish(session, Reason.REVOKED)
            raise TerminalClosed()
        return session

    def output(self, identifier: str, cursor: int) -> dict[str, Any]:
        session = self.get(identifier)
        with SHELLS.waiting(session) as waits:
            data, following, skipped = session.read(cursor, LONG_POLL if waits else 0)
        closed = session.drained(following)
        if closed:
            finish(session)
        return {
            "data": base64.b64encode(data).decode("ascii"),
            "cursor": following,
            "skipped": skipped,
            "closed": closed,
            "reason": session.reason if closed else "",
            "exit_status": session.exit_status if closed else None,
        }

    def input(self, identifier: str, seq: int, data: str) -> bool:
        sent = data.encode("utf-8")
        if len(sent) > INPUT_MAX:
            raise ValidationError(
                {"data": [ErrorDetail(INPUT_TOO_LARGE, code="input_too_large")]}
            )
        return self.get(identifier).write(seq, sent)

    def resize(self, identifier: str, cols: int, rows: int) -> ShellSession:
        session = self.get(identifier)
        session.resize(cols, rows)
        return session

    def close(self, identifier: str) -> None:
        finish(self.get(identifier), Reason.CLOSED)

    def _allowed(self) -> str | None:
        if not self._signed_in():
            raise TerminalNeedsAccount()
        policy = terminal_policy()
        if policy == OFF:
            raise TerminalOff()
        role = role_of(self.user)
        if policy == MASTER and role != Role.MASTER:
            raise RoleRequired(Role.MASTER, role)
        return role

    def _still_allowed(self, session: ShellSession) -> bool:
        return still_allowed(session, self.session_key)

    def _signed_in(self) -> bool:
        return self.user is not None and bool(getattr(self.user, "is_authenticated", False))

    def _place(
        self, mode: str, server: UUID | None, application: UUID | None
    ) -> tuple[Any, Place, str | None]:
        if mode == SERVER and server is not None:
            found = ServerService(self.user).get(server)
            return found, Place(SERVER, str(found.pk), "", found.name, ""), None
        if mode != APPLICATION or application is None:
            raise ValidationError({"mode": [ErrorDetail(PLACE_REQUIRED, code="required")]})
        chosen = ApplicationService(self.user).get(application)
        target = container_of(chosen)
        cwd = chosen.project_dir or None
        if target is None:
            command = build_script(["sh", "-c", HOST_SHELL], cwd=cwd)
        else:
            command = build_script(
                terminal_command(target, ["sh", "-c", CONTAINER_SHELL]), cwd=cwd
            )
        place = Place(
            APPLICATION,
            str(chosen.server_id),
            str(chosen.pk),
            chosen.name,
            "" if target is None else target.name,
        )
        return chosen, place, command


def still_allowed(session: ShellSession, session_key: str | None = None) -> bool:
    if session_key is not None and session_key != session.owner.session_key:
        return False
    user = (
        get_user_model()
        ._default_manager.filter(pk=session.owner.user_id, is_active=True)
        .first()
    )
    if user is None or user.password != session.owner.password:
        return False
    role = role_of(user)
    policy = terminal_policy()
    return (
        role == session.owner.role
        and policy != OFF
        and allows(role, Capability.SHELL_OPEN)
        and (policy != MASTER or role == Role.MASTER)
    )


def finish(session: ShellSession, reason: str | None = None) -> None:
    if reason:
        session.end(reason)
    with session.finishing:
        if session.finished:
            return
        session.finished = True
    session.end(Reason.CLOSED)
    session.release()
    SHELLS.forget(session)
    audit.finish(session.activity_id, data={**session.started, **session.summary()})


def sweep_terminals() -> int:
    finished = 0
    for session in SHELLS.every():
        if not session.closed:
            reason = session.overdue() or (
                "" if still_allowed(session) else Reason.REVOKED
            )
            if reason:
                finish(session, reason)
                finished += 1
        elif session.clock() - session.last_poll_at >= UNPOLLED_SECONDS:
            finish(session)
            finished += 1
    return finished


def close_signed_out(sender: Any, request: Any = None, user: Any = None, **kwargs: Any) -> None:
    if user is None or request is None:
        return
    key = getattr(getattr(request, "session", None), "session_key", None) or ""
    for session in SHELLS.owned_by(user.pk):
        if session.owner.session_key == key:
            finish(session, Reason.SIGNED_OUT)


def stop_terminals() -> int:
    every = SHELLS.every()
    for session in every:
        finish(session, Reason.STOPPED)
    return len(every)
