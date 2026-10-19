from __future__ import annotations

from typing import Any

from dbs.manager.applications.models import Application
from dbs.manager.servers.models import Server


def problem(application: Application) -> str:
    if application.last_check_status == Application.CheckStatus.OK:
        return ""
    report = application.last_check_report or {}
    problems = []
    container = _container_problem(application, report.get("container"))
    if container:
        problems.append(container)
    else:
        if report.get("dbs_version") is None:
            problems.append(_missing_dbs(application, report))
        if report.get("backup_command") is False:
            problems.append("manage.py dbs_backup does not run")
    if report.get("env_file") is False:
        problems.append(f"{application.env_path} is missing")
    problems += [
        f"{root} is missing"
        for root, ready in report.get("roots", {}).items()
        if not ready
    ]
    if report and not report.get("remote_backup_dir"):
        problems.append(f"{application.remote_backup_dir} is missing")
    return "; ".join(problems) or application.last_check_error


def server_problem(server: Server) -> str:
    if server.last_check_status == Server.CheckStatus.OK:
        return ""
    report = server.last_check_report or {}
    if report and not report.get("system"):
        return "the server did not answer uname"
    return server.last_check_error


def engines_label(engines: dict[str, Any]) -> str:
    found = [
        f"{engine} {facts.get('version') or ''}".strip()
        for engine, facts in sorted((engines or {}).items())
        if facts.get("usable")
    ]
    return ", ".join(found) or "-"


def _container_problem(
    application: Application, container: dict[str, Any] | None
) -> str:
    if container is None:
        return ""
    reason = f" ({container['error']})" if container.get("error") else ""
    engine = container.get("engine") or application.engine
    if container.get("version") is None:
        return (
            f"{engine} does not run for {application.server.username}{reason}"
        )
    if not container.get("running"):
        name = application.compose_service or application.container_name
        return f"{name} is not running{reason}"
    return ""


def _missing_dbs(application: Application, report: dict[str, Any]) -> str:
    suggestion = report.get("python_suggestion")
    if suggestion:
        other = suggestion["python_path"]
        return (
            f"django-dbs is not in {application.python_path} but {other} has it; "
            f"set the application's Python to {other}"
        )
    error = report.get("dbs_error")
    reason = f" ({error})" if error else ""
    name = application.compose_service or application.container_name
    where = f" in {name}" if application.in_container else ""
    return f"django-dbs is not installed for {application.python_path}{where}{reason}"
