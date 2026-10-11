from __future__ import annotations

from typing import Any

from dbs.manager.servers.models import Server


def problem(server: Server) -> str:
    if server.last_check_status == Server.CheckStatus.OK:
        return ""
    report = server.last_check_report or {}
    problems = []
    compose = _compose_problem(server, report.get("compose"))
    if compose:
        problems.append(compose)
    else:
        if report.get("dbs_version") is None:
            problems.append(_missing_dbs(server, report))
        if report.get("backup_command") is False:
            problems.append("manage.py dbs_backup does not run")
    if report.get("env_file") is False:
        problems.append(f"{server.env_path} is missing")
    problems += [
        f"{root} is missing"
        for root, ready in report.get("roots", {}).items()
        if not ready
    ]
    if report and not report.get("remote_backup_dir"):
        problems.append(f"{server.remote_backup_dir} is missing")
    return "; ".join(problems) or server.last_check_error


def _compose_problem(server: Server, compose: dict[str, Any] | None) -> str:
    if compose is None:
        return ""
    reason = f" ({compose['error']})" if compose.get("error") else ""
    if compose.get("version") is None:
        return f"docker compose does not run for {server.username}{reason}"
    if not compose.get("running"):
        return f"the {server.compose_service} service is not running{reason}"
    return ""


def _missing_dbs(server: Server, report: dict[str, Any]) -> str:
    suggestion = report.get("python_suggestion")
    if suggestion:
        other = suggestion["python_path"]
        return (
            f"django-dbs is not in {server.python_path} but {other} has it; "
            f"set the server's Python to {other}"
        )
    error = report.get("dbs_error")
    reason = f" ({error})" if error else ""
    where = f" in the {server.compose_service} service" if server.in_compose else ""
    return f"django-dbs is not installed for {server.python_path}{where}{reason}"
