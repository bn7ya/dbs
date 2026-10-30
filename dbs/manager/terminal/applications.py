from __future__ import annotations

from typing import Any

from dbs.manager.adapters import applications, references
from dbs.manager.adapters.forms import validated
from dbs.manager.applications.deployment import QUESTIONS
from dbs.manager.applications.serializers import (
    ApplicationListSerializer,
    ApplicationSerializer,
    ApplicationUpdateSerializer,
)
from dbs.manager.applications.services import ApplicationService
from dbs.manager.terminal import CommandFailed
from dbs.manager.terminal.session import TerminalSession

SETTING_FIELDS = (
    "kind",
    "engine",
    "compose_project",
    "compose_service",
    "compose_files",
    "container_name",
    "project_dir",
    "workdir",
    "python_path",
    "manage_path",
    "settings_module",
    "remote_backup_dir",
    "env_path",
    "env_location",
    "file_roots",
)
SHOWN_FIELDS = (
    "id",
    "name",
    "server",
    "kind",
    "engine",
    "compose_project",
    "compose_service",
    "compose_files",
    "container_name",
    "project_dir",
    "workdir",
    "python_path",
    "manage_path",
    "settings_module",
    "remote_backup_dir",
    "mounts",
    "env_path",
    "env_location",
    "file_roots",
    "deployment",
    "detected",
    "last_check_status",
    "last_check_error",
    "last_checked_at",
    "timeout_in_container",
)
LIST_COLUMNS = (
    ("NAME", "name"),
    ("SERVER", lambda row: row["server"]["name"]),
    ("RUNS", lambda row: runs_in(row)),
    ("STATUS", "last_check_status"),
    ("CHECKED", "last_checked_at"),
    ("ID", "id"),
)
CANDIDATE_COLUMNS = (
    ("N", "number"),
    ("RUNS", "runs"),
    ("PYTHON", "python_path"),
    ("DJANGO-DBS", "dbs_version"),
    ("SETTINGS", "settings_module"),
    ("BACKUPS", "backup_dir_on_host"),
    ("PROBLEMS", "problems"),
)
CHECK_COLUMNS = (
    ("APPLICATION", "name"),
    ("SERVER", "server"),
    ("CONNECTION", "connection"),
    ("STATUS", "status"),
    ("DJANGO-DBS", "remote_version"),
    ("PROBLEM", "problem"),
)


def runs_in(row: dict[str, Any]) -> str:
    if row["kind"] == "compose":
        return f"{row['engine']} compose {row['compose_service']}"
    if row["kind"] == "container":
        return f"{row['engine']} {row['container_name']}"
    return row.get("project_dir") or "on the server"


def list_applications(session: TerminalSession) -> int:
    args = session.args
    server = references.server(session.user, args.server) if args.server else None
    found = ApplicationService(session.user).list(
        args.search, None if server is None else server.pk
    )
    rows = ApplicationListSerializer(found, many=True).data
    session.out.table(
        rows,
        LIST_COLUMNS,
        empty="No applications yet. Add one with: django_dbs app add",
    )
    return 0


def show(session: TerminalSession) -> int:
    application = references.application(session.user, session.args.application)
    data = ApplicationSerializer(application).data
    if session.out.as_json:
        session.out.json(data)
        return 0
    detected = (data.get("last_check_report") or {}).get("detected") or {}
    session.out.fields(
        {
            **data,
            "server": data["server"]["name"],
            "deployment": _answers(data["deployment"]),
            "detected": _answers(detected),
        },
        SHOWN_FIELDS,
    )
    return 0


def discover(session: TerminalSession) -> int:
    args = session.args
    server = references.server(session.user, args.server)
    answers = _deployment_answers(args)
    report = session.guarded(
        lambda password: applications.discover(
            session.user, server, args.folder, account_password=password, deployment=answers
        )
    )
    if session.out.as_json:
        session.out.json(report)
        return 0
    _print_report(session, report)
    return 0


def add(session: TerminalSession) -> int:
    args = session.args
    server = references.server(session.user, args.server)
    given = _given_settings(args)
    report = session.guarded(
        lambda password: applications.discover(
            session.user,
            server,
            args.folder,
            account_password=password,
            deployment=given.get("deployment"),
        )
    )
    if args.backup_passphrase:
        given["backup_passphrase"] = session.secret("Backup passphrase")
    added = session.guarded(
        lambda password: applications.add(
            session.user,
            server,
            report,
            name=args.name,
            choice=args.candidate,
            given=given,
            account_password=password,
        )
    )
    application = added.application
    _say(session, f"Added {application.name}: {runs_in(added.candidate)}.")
    [checked] = applications.checked(session.user, [application])
    if session.out.as_json:
        session.out.json(
            {**ApplicationSerializer(application).data, "check": checked.result}
        )
        return 0
    session.out.table([_row(checked)], CHECK_COLUMNS, empty="")
    return 0 if checked.ok else 1


def edit(session: TerminalSession) -> int:
    args = session.args
    application = references.application(session.user, args.application)
    body: dict[str, Any] = {
        key: value
        for key, value in {"name": args.name, **_given_settings(args)}.items()
        if value is not None
    }
    if not body:
        raise CommandFailed("nothing to change; pass at least one option.")
    changes = validated(ApplicationUpdateSerializer, body, partial=True)
    service = ApplicationService(session.user)
    saved = session.guarded(
        lambda password: service.update(
            application.pk, account_password=password, **changes
        )
    )
    session.out.say(f"Saved {saved.name}.", ApplicationSerializer(saved).data)
    return 0


def remove(session: TerminalSession) -> int:
    application = references.application(session.user, session.args.application)
    session.confirm(
        f"Type the application's name ({application.name}) to remove it:",
        expected=application.name,
    )
    service = ApplicationService(session.user)
    session.guarded(
        lambda password: service.delete(application.pk, account_password=password)
    )
    session.out.say(f"Removed {application.name}.", {"removed": str(application.pk)})
    return 0


def check(session: TerminalSession) -> int:
    chosen = references.applications(
        session.user, session.args.applications, session.args.all
    )
    done = applications.checked(session.user, chosen)
    session.out.table(
        [_row(item) for item in done],
        CHECK_COLUMNS,
        empty="",
        data=[item.result for item in done],
    )
    return 0 if all(item.ok for item in done) else 1


def passphrase(session: TerminalSession) -> int:
    application = references.application(session.user, session.args.application)
    shown = ApplicationService(session.user).reveal_passphrase(
        application.pk, session.password()
    )
    session.out.say(shown, {"passphrase": shown})
    return 0


def capture_passphrase(session: TerminalSession) -> int:
    application = references.application(session.user, session.args.application)
    ApplicationService(session.user).capture_passphrase(application.pk)
    session.out.say(
        f"Read the backup passphrase from {application.name}.", {"captured": True}
    )
    return 0


def _print_report(session: TerminalSession, report: dict[str, Any]) -> None:
    if not report["listing"]:
        folders = report.get("folders") or []
        if folders:
            session.out.line("Folders that look like projects:")
            for folder in folders:
                session.out.line(f"  {folder}")
        else:
            session.out.line("Name the application's folder with --folder.")
        return
    session.out.line(f"Folder  {report['folder']}")
    if not report["trusted"]:
        session.out.line(
            "This folder or its parent can be written by others, so nothing in it "
            "was run."
        )
        return
    rows = [
        {
            **candidate,
            "number": number,
            "runs": runs_in(candidate),
            "problems": ", ".join(candidate["problems"]),
        }
        for number, candidate in enumerate(report["candidates"], start=1)
    ]
    session.out.table(rows, CANDIDATE_COLUMNS, empty="Found no Django project here.")
    for number, candidate in enumerate(report["candidates"], start=1):
        for mismatch in candidate.get("mismatches") or []:
            session.out.line(
                f"{number}: you said {mismatch['field']} is {mismatch['said']}, "
                f"found {mismatch['found']}."
            )


def _given_settings(args: Any) -> dict[str, Any]:
    given = {
        field: getattr(args, field)
        for field in SETTING_FIELDS
        if getattr(args, field, None) is not None
    }
    answers = _deployment_answers(args)
    if answers is not None:
        given["deployment"] = answers
    return given


def _deployment_answers(args: Any) -> dict[str, str] | None:
    given = getattr(args, "deployment_answers", None)
    if not given:
        return None
    answers: dict[str, str] = {}
    for item in given:
        key, separator, value = item.partition("=")
        key = key.strip().replace("-", "_")
        if not separator or key not in QUESTIONS:
            raise CommandFailed(
                f"--deployment takes KEY=VALUE with KEY one of {', '.join(QUESTIONS)}."
            )
        answers[key] = value.strip()
    return answers


def _answers(answers: dict[str, str]) -> str:
    return ", ".join(f"{key}={value}" for key, value in answers.items() if value)


def _row(item: applications.CheckedApplication) -> dict[str, Any]:
    return {
        "name": item.name,
        "server": item.server,
        "connection": item.connection,
        "status": item.status,
        "remote_version": item.remote_version,
        "problem": item.problem,
    }


def _say(session: TerminalSession, message: str) -> None:
    if not session.out.as_json:
        session.out.line(message)
