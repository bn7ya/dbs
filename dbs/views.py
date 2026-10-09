from __future__ import annotations

import hashlib
import json
import os

from django.contrib import messages
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.http.request import RawPostDataException
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST

from . import audit
from .conf import setting
from .engine import create_backup, restore_backup
from .exceptions import DBSError
from .forms import CreateBackupForm, RestoreRecordForm, RestoreUploadForm, SetupForm
from .keys import with_passphrase
from .models import (
    AnomalyEvent,
    AuditEvent,
    BackupRecord,
    BackupTarget,
    KnownLocation,
    SecurityPolicy,
)
from .naming import backup_filename
from .security import geo, guard
from .security.decorators import superuser_required

DEFAULT_MAX_UPLOAD_BYTES = 1024 ** 3

CONSOLE_ACTIONS = {
    "check": "Check the connection",
    "version": "Show the DBS version on the server",
    "ensure_dir": "Create the remote backup directory",
    "remote_backup": "Run manage.py dbs backup on the server",
    "list": "List remote backups",
}


def _audit(request, action, target="", detail="", succeeded=True, data=None):
    from .security.features import client_address

    audit.record(
        action,
        actor=request.user,
        target=target,
        detail=detail,
        data=data,
        status=audit.SUCCEEDED if succeeded else audit.FAILED,
        remote_addr=client_address(request),
    )


def _page(request, template, context):
    from django.contrib import admin

    merged = dict(admin.site.each_context(request))
    merged.update(context)
    return render(request, template, merged)


@superuser_required
@never_cache
@require_http_methods(["GET", "POST"])
def setup(request):
    policy = SecurityPolicy.load()
    if request.method == "POST":
        form = SetupForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            policy.apply_level(data["level"])
            policy.expected_networks = data["expected_networks"]
            policy.trusted_networks = data["trusted_networks"]
            policy.notify_emails = data["notify_emails"]
            policy.collect_location = bool(data["collect_location"]) and geo.enabled()
            policy.configured = True
            policy.configured_by = request.user
            policy.save()
            if policy.collect_location and data.get("latitude") is not None:
                KnownLocation.objects.update_or_create(
                    user=request.user,
                    label="usual",
                    defaults={
                        "latitude": round(data["latitude"], geo.COORDINATE_PRECISION),
                        "longitude": round(data["longitude"], geo.COORDINATE_PRECISION),
                    },
                )
            _audit(request, "security.setup", detail=f"level={policy.level}")
            messages.success(request, "DBS security is configured.")
            return redirect("admin:app_list", app_label="dbs")
    else:
        form = SetupForm(
            initial={
                "level": policy.level,
                "expected_networks": policy.expected_networks,
                "trusted_networks": policy.trusted_networks,
                "notify_emails": policy.notify_emails,
            }
        )
    return _page(
        request,
        "admin/dbs/setup.html",
        {"title": "Set up DBS security", "form": form, "geolocation": geo.enabled()},
    )


@superuser_required
@never_cache
@require_POST
def guard_check(request):
    try:
        payload = json.loads(request.body or b"{}")
    except (ValueError, RawPostDataException):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    verdict = guard.evaluate(request, action="view", location=payload.get("location"))
    guard.apply(verdict, request)
    return JsonResponse(
        {
            "authorized": verdict.level != guard.BLOCK,
            "action": verdict.action,
            "reasons": verdict.reasons,
            "poll_after": int(setting("DBS_GUARD_POLL_SECONDS", 15)),
            "wants_location": geo.enabled() and SecurityPolicy.load().collect_location,
        }
    )


@superuser_required
@never_cache
@require_http_methods(["GET", "POST"])
def create_backup_view(request):
    form = CreateBackupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            container = create_backup(
                data["passphrase"] or _default_passphrase(),
                using=data["database"],
            )
        except DBSError as exc:
            _audit(request, "backup.create", detail=str(exc), succeeded=False)
            messages.error(request, f"Backup failed: {exc}")
            return redirect("admin:dbs_backup_create")

        name = backup_filename()
        digest = hashlib.sha256(container).hexdigest()
        if data["destination"]:
            target = BackupTarget.objects.get(pk=data["destination"])
            return _push(request, container, name, digest, target, data)
        BackupRecord.objects.create(
            filename=name,
            size_bytes=len(container),
            sha256=digest,
            database=data["database"],
            created_by=request.user,
            location="",
            note=data["note"],
        )
        _audit(
            request,
            "backup.create",
            target=name,
            detail=f"{len(container)} bytes",
            data={
                "file": name,
                "size": len(container),
                "sha256": digest,
                "database": data["database"],
            },
        )
        response = HttpResponse(container, content_type="application/octet-stream")
        response["Content-Disposition"] = f'attachment; filename="{name}"'
        return response
    return _page(
        request,
        "admin/dbs/create_backup.html",
        {"title": "Take a backup", "form": form},
    )


def _push(request, container, name, digest, target, data):
    from .transports.ssh import open_session

    try:
        with open_session(target.ssh_target()) as session:
            remote = session.push(container, name)
    except DBSError as exc:
        _audit(request, "backup.push", target=target.name, detail=str(exc), succeeded=False)
        messages.error(request, f"Push failed: {exc}")
        return redirect("admin:dbs_backup_create")
    BackupRecord.objects.create(
        filename=name,
        size_bytes=len(container),
        sha256=digest,
        target=target,
        database=data["database"],
        created_by=request.user,
        location=remote,
        note=data["note"],
    )
    _audit(request, "backup.push", target=target.name, detail=remote)
    messages.success(request, f"Backup pushed to {target.name} as {remote}.")
    return redirect("admin:dbs_backuprecord_changelist")


def _default_passphrase():
    from .keys import default_passphrase

    return default_passphrase()


@superuser_required
@never_cache
@require_http_methods(["GET", "POST"])
def restore_view(request):
    form = RestoreUploadForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        upload = form.cleaned_data["backup"]
        limit = int(setting("DBS_MAX_UPLOAD_BYTES", DEFAULT_MAX_UPLOAD_BYTES))
        if upload.size > limit:
            messages.error(request, f"Upload is larger than the {limit} byte limit.")
            return redirect("admin:dbs_backup_restore")
        data = upload.read()
        try:
            result = with_passphrase(
                lambda secret: restore_backup(
                    data,
                    secret,
                    dry_run=form.cleaned_data["dry_run"],
                    flush=form.cleaned_data["flush"],
                ),
                form.cleaned_data["passphrase"] or None,
            )
        except DBSError as exc:
            _audit(request, "backup.restore", detail=str(exc), succeeded=False)
            messages.error(request, f"Restore failed: {exc}")
            return redirect("admin:dbs_backup_restore")

        summary = _restore_summary(result, form.cleaned_data["dry_run"])
        _audit(request, "backup.restore", target=upload.name or "upload", detail=summary)
        messages.success(request, summary)
        return redirect("admin:dbs_backup_restore")
    return _page(
        request,
        "admin/dbs/restore.html",
        {"title": "Restore from an uploaded backup", "form": form},
    )


def _restore_summary(result, dry_run):
    if dry_run:
        return (
            f"Dry run: {result.records_would_load} records and "
            f"{result.files_would_write} files would be restored; nothing changed."
        )
    healed = " Corruption was detected and repaired." if result.healed else ""
    return (
        f"Restored {result.records_loaded} records and "
        f"{result.files_written} files.{healed}"
    )


@superuser_required
@never_cache
@require_http_methods(["GET", "POST"])
def restore_record(request, pk):
    record = BackupRecord.objects.filter(pk=pk).first()
    path = record.local_path() if record is not None else None
    if path is None:
        raise Http404
    form = RestoreRecordForm(request.POST or None, filename=record.filename)
    if request.method == "POST" and form.is_valid():
        dry_run = form.cleaned_data["dry_run"]
        with open(path, "rb") as fh:
            data = fh.read()
        details = {
            "file": record.filename,
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "dry_run": dry_run,
            "flushed": form.cleaned_data["flush"],
        }
        try:
            result = with_passphrase(
                lambda secret: restore_backup(
                    data, secret, dry_run=dry_run, flush=form.cleaned_data["flush"]
                ),
                form.cleaned_data["passphrase"] or None,
            )
        except DBSError as exc:
            _audit(
                request,
                "backup.restore",
                target=record.filename,
                detail=str(exc),
                succeeded=False,
                data=details,
            )
            messages.error(request, f"Restore failed: {exc}")
            return redirect("admin:dbs_backup_restore_record", pk=record.pk)
        summary = _restore_summary(result, dry_run)
        _audit(request, "backup.restore", target=record.filename, detail=summary, data=details)
        messages.success(request, summary)
        return redirect("admin:dbs_backup_restore_record", pk=record.pk)
    return _page(
        request,
        "admin/dbs/restore_record.html",
        {"title": f"Restore {record.filename}", "form": form, "record": record},
    )


@superuser_required
@never_cache
def health(request):
    from .health import report

    return _page(
        request,
        "admin/dbs/health.html",
        {"title": "Backup health", "report": report()},
    )


@superuser_required
@never_cache
def connection(request):
    from .connection import details

    info = details()
    return _page(
        request,
        "admin/dbs/connection.html",
        {
            "title": "Connection details",
            "details": info,
            "snippet": json.dumps(info, indent=2),
        },
    )


@superuser_required
@never_cache
def download(request, pk):
    record = BackupRecord.objects.filter(pk=pk).first()
    if record is None:
        raise Http404
    path = record.local_path()
    if path is None:
        raise Http404
    verdict = guard.evaluate(request, action="download")
    guard.apply(verdict, request)
    if verdict.level == guard.BLOCK:
        raise Http404
    _audit(request, "backup.download", target=record.filename)
    response = FileResponse(
        open(path, "rb"),
        as_attachment=True,
        filename=os.path.basename(path),
        content_type="application/octet-stream",
    )
    return response


@superuser_required
@never_cache
@require_http_methods(["GET", "POST"])
def console(request, pk):
    target = BackupTarget.objects.filter(pk=pk).first()
    if target is None:
        raise Http404
    shell_enabled = bool(setting("DBS_ADMIN_CONSOLE_SHELL", False))
    if request.method == "POST":
        return _run_console(request, target, shell_enabled)
    return _page(
        request,
        "admin/dbs/console.html",
        {
            "title": f"Console — {target.name}",
            "target": target,
            "actions": CONSOLE_ACTIONS,
            "shell_enabled": shell_enabled,
        },
    )


def _run_console(request, target, shell_enabled):
    from .transports.ssh import open_session

    command = request.POST.get("command", "").strip()
    action = "" if command else request.POST.get("action", "")
    label = "console.shell" if command else f"console.{action}"
    if command and not shell_enabled:
        _audit(request, "console.shell", target=target.name, detail="refused", succeeded=False)
        return JsonResponse(
            {
                "ok": False,
                "output": (
                    "Free-form commands are disabled. Set DBS_ADMIN_CONSOLE_SHELL = True "
                    "to allow them."
                ),
            },
            status=403,
        )
    if not command and action not in CONSOLE_ACTIONS:
        return JsonResponse({"ok": False, "output": "Unknown action."}, status=400)

    try:
        with open_session(target.ssh_target()) as session:
            output, ok = _console_output(session, target, action, command)
    except Exception as exc:
        _audit(request, label, target=target.name, detail=str(exc), succeeded=False)
        return JsonResponse({"ok": False, "output": str(exc)}, status=200)

    _audit(request, label, target=target.name, detail=command or action, succeeded=ok)
    return JsonResponse({"ok": ok, "output": output})


def _console_output(session, target, action, command):
    if command:
        result = session.run(command)
        return _render_result(result), result.ok
    if action == "check":
        from .transports.ssh import check_connection

        report = check_connection(target.ssh_target())
        return "\n".join(f"{key}: {value}" for key, value in report.items()), True
    if action == "version":
        result = session.run("python -c 'import dbs; print(dbs.__version__)'")
        return _render_result(result), result.ok
    if action == "ensure_dir":
        return f"remote directory ready: {session.ensure_dir()}", True
    if action == "remote_backup":
        result = session.run("python manage.py dbs backup --help")
        return _render_result(result), result.ok
    if action == "list":
        names = session.names()
        return "\n".join(names) or "no backups found", True
    return "Unknown action.", False


def _render_result(result):
    parts = [result.stdout or "", result.stderr or ""]
    body = "\n".join(part for part in parts if part).strip()
    return body or f"exit status {result.exit_status}"


@superuser_required
@never_cache
def wiki(request, page="index"):
    pages = {
        "index": "Overview",
        "getting-started": "Getting started",
        "passphrases": "Passphrases and SECRET_KEY",
        "targets": "SFTP targets and the console",
        "scheduling": "Scheduled backups",
        "manager": "The DBS manager",
        "restore": "Restoring",
        "commands": "Command reference",
        "upgrading": "Upgrading",
        "security": "The session guard",
        "privacy": "What the guard collects",
        "ai": "Working with AI assistants",
        "troubleshooting": "Troubleshooting",
    }
    if page not in pages:
        raise Http404
    return _page(
        request,
        f"admin/dbs/wiki/{page}.html",
        {"title": f"DBS wiki — {pages[page]}", "pages": pages, "current": page},
    )


@superuser_required
@never_cache
def security_overview(request):
    return _page(
        request,
        "admin/dbs/security.html",
        {
            "title": "DBS security",
            "policy": SecurityPolicy.load(),
            "anomalies": AnomalyEvent.objects.select_related("user")[:50],
            "audit": AuditEvent.objects.select_related("actor")[:50],
            "geolocation": geo.enabled(),
        },
    )
