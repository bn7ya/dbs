from __future__ import annotations

import json
import os

from django.contrib import messages
from django.http import FileResponse, Http404, JsonResponse
from django.http.request import RawPostDataException
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST

from . import audit, jobs
from .conf import setting
from .exceptions import DBSError
from .forms import CreateBackupForm, RestoreRecordForm, RestoreUploadForm, SetupForm
from .models import (
    AnomalyEvent,
    AuditEvent,
    BackupRecord,
    KnownLocation,
    SecurityPolicy,
)
from .security import geo, guard
from .security.decorators import superuser_required

DEFAULT_MAX_UPLOAD_BYTES = 1024 ** 3
JOB_REFRESH_SECONDS = 3


def _audit(request, action, target="", detail="", succeeded=True, data=None, error_code=""):
    from .security.features import client_address

    return audit.record(
        action,
        actor=request.user,
        target=target,
        detail=detail,
        data=audit.with_actor(data, request.user),
        status=audit.SUCCEEDED if succeeded else audit.FAILED,
        error_code=error_code,
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
            located = policy.collect_location and data.get("latitude") is not None
            if located:
                KnownLocation.objects.update_or_create(
                    user=request.user,
                    label="usual",
                    defaults={
                        "latitude": round(data["latitude"], geo.COORDINATE_PRECISION),
                        "longitude": round(data["longitude"], geo.COORDINATE_PRECISION),
                    },
                )
            _audit(
                request,
                "security.setup",
                detail=f"level={policy.level}",
                data={
                    "level": policy.level,
                    "collect_location": policy.collect_location,
                    "known_location": bool(located),
                },
            )
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
    from .schedule_runner import backup_directory

    directory = backup_directory()
    form = CreateBackupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            event_id = jobs.start_backup(
                database=data["database"],
                passphrase=data["passphrase"],
                note=data["note"],
                **_actor(request),
            )
        except DBSError as exc:
            messages.error(request, f"The backup did not start: {exc}")
            return redirect("admin:dbs_backup_create")
        return redirect("admin:dbs_job", pk=event_id)
    return _page(
        request,
        "admin/dbs/create_backup.html",
        {"title": "Take a backup", "form": form, "directory": directory},
    )


def _actor(request):
    from .security.features import client_address

    return {"actor": request.user, "remote_addr": client_address(request)}


@superuser_required
@never_cache
@require_http_methods(["GET", "POST"])
def restore_view(request):
    from .schedule_runner import backup_directory

    form = RestoreUploadForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        upload = form.cleaned_data["backup"]
        limit = int(setting("DBS_MAX_UPLOAD_BYTES", DEFAULT_MAX_UPLOAD_BYTES))
        if upload.size > limit:
            messages.error(request, f"Upload is larger than the {limit} byte limit.")
            return redirect("admin:dbs_backup_restore")
        try:
            path = jobs.keep_upload(upload, backup_directory())
        except OSError as exc:
            messages.error(request, f"The upload could not be stored: {exc.strerror or exc}")
            return redirect("admin:dbs_backup_restore")
        try:
            event_id = jobs.start_restore(
                path=path,
                name=os.path.basename(upload.name or "upload.dbs"),
                passphrase=form.cleaned_data["passphrase"],
                dry_run=form.cleaned_data["dry_run"],
                flush=form.cleaned_data["flush"],
                owned=True,
                **_actor(request),
            )
        except DBSError as exc:
            messages.error(request, f"The restore did not start: {exc}")
            return redirect("admin:dbs_backup_restore")
        return redirect("admin:dbs_job", pk=event_id)
    return _page(
        request,
        "admin/dbs/restore.html",
        {"title": "Restore from an uploaded backup", "form": form},
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
        try:
            event_id = jobs.start_restore(
                path=path,
                name=record.filename,
                passphrase=form.cleaned_data["passphrase"],
                dry_run=form.cleaned_data["dry_run"],
                flush=form.cleaned_data["flush"],
                **_actor(request),
            )
        except DBSError as exc:
            messages.error(request, f"The restore did not start: {exc}")
            return redirect("admin:dbs_backup_restore_record", pk=record.pk)
        return redirect("admin:dbs_job", pk=event_id)
    return _page(
        request,
        "admin/dbs/restore_record.html",
        {"title": f"Restore {record.filename}", "form": form, "record": record},
    )


@superuser_required
@never_cache
def job(request, pk):
    event = (
        AuditEvent.objects.filter(pk=pk, action__in=jobs.PANEL_ACTIONS)
        .select_related("actor")
        .first()
    )
    if event is None:
        raise Http404
    if event.status in audit.UNFINISHED:
        jobs.recover()
        event.refresh_from_db()
    running = event.status in audit.UNFINISHED
    record = None
    if event.action == jobs.BACKUP and event.status == audit.SUCCEEDED:
        record = next(
            (
                candidate
                for candidate in BackupRecord.objects.filter(filename=event.target_name)
                if candidate.local_path() is not None
            ),
            None,
        )
    return _page(
        request,
        "admin/dbs/job.html",
        {
            "title": "Backup" if event.action == jobs.BACKUP else "Restore",
            "event": event,
            "running": running,
            "summary": jobs.describe(event),
            "record": record,
            "refresh_seconds": JOB_REFRESH_SECONDS,
        },
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
        {"title": "Connection details", "details": info},
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
    _audit(
        request,
        "backup.download",
        target=record.filename,
        data={"file": record.filename, "size": record.size_bytes, "sha256": record.sha256},
    )
    response = FileResponse(
        open(path, "rb"),
        as_attachment=True,
        filename=os.path.basename(path),
        content_type="application/octet-stream",
    )
    return response


@superuser_required
@never_cache
def wiki(request, page="index"):
    pages = {
        "index": "Overview",
        "getting-started": "Getting started",
        "passphrases": "Passphrases and SECRET_KEY",
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
