from __future__ import annotations

import datetime

from django.conf import settings
from django.contrib.auth.decorators import user_passes_test
from django.http import HttpResponse
from django.template import RequestContext, Template
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_http_methods

from ..engine import create_backup, restore_backup
from ..exceptions import DBSError

DEFAULT_MAX_UPLOAD_BYTES = 1024 ** 3

_PAGE = Template(
    """
<!doctype html><html><head><title>DBS {{ title }}</title>
<style>body{font-family:sans-serif;max-width:640px;margin:3rem auto}
label{display:block;margin:.6rem 0 .2rem} input{padding:.4rem;width:100%}
button{margin-top:1rem;padding:.5rem 1rem} .msg{padding:.6rem;border-radius:4px}
.err{background:#fde8e8;color:#9b1c1c} .ok{background:#e6f4ea;color:#1e6b32}</style>
</head><body><h1>DBS {{ title }}</h1>
{% if message %}<p class="msg {{ message_kind }}">{{ message }}</p>{% endif %}
<form method="post"{% if multipart %} enctype="multipart/form-data"{% endif %}>
{% csrf_token %}{{ fields }}<button type="submit">{{ title }}</button></form>
</body></html>
"""
)


def _render(request, title, fields, *, multipart=False, message="", message_kind="err"):
    context = RequestContext(
        request,
        {
            "title": title,
            "fields": mark_safe(fields),
            "multipart": multipart,
            "message": message,
            "message_kind": message_kind,
        },
    )
    return HttpResponse(_PAGE.render(context))


def _superuser_required(view):
    return user_passes_test(lambda u: u.is_active and u.is_superuser)(view)


@_superuser_required
@require_http_methods(["GET", "POST"])
def backup_download(request):
    fields = (
        '<label>Passphrase</label><input type="password" name="passphrase" required>'
        '<label>Confirm passphrase</label><input type="password" name="passphrase2" required>'
    )
    if request.method == "GET":
        return _render(request, "Backup", fields)

    passphrase = request.POST.get("passphrase", "")
    if not passphrase or passphrase != request.POST.get("passphrase2"):
        return _render(
            request, "Backup", fields,
            message="Passphrases are empty or do not match.",
        )
    try:
        container = create_backup(passphrase)
    except DBSError as exc:
        return _render(request, "Backup", fields, message=str(exc))

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    response = HttpResponse(container, content_type="application/octet-stream")
    response["Content-Disposition"] = f'attachment; filename="backup-{stamp}.dbs"'
    return response


@_superuser_required
@require_http_methods(["GET", "POST"])
def restore_upload(request):
    fields = (
        '<label>Backup file (.dbs)</label><input type="file" name="backup" required>'
        '<label>Passphrase</label><input type="password" name="passphrase" required>'
    )
    if request.method == "GET":
        return _render(request, "Restore", fields, multipart=True)

    upload = request.FILES.get("backup")
    passphrase = request.POST.get("passphrase", "")
    if not upload or not passphrase:
        return _render(
            request, "Restore", fields, multipart=True,
            message="A file and passphrase are required.",
        )
    max_bytes = getattr(settings, "DBS_MAX_UPLOAD_BYTES", DEFAULT_MAX_UPLOAD_BYTES)
    if upload.size > max_bytes:
        return _render(
            request, "Restore", fields, multipart=True,
            message=f"Upload is larger than the {max_bytes} byte limit.",
        )
    try:
        result = restore_backup(upload.read(), passphrase)
    except DBSError as exc:
        return _render(
            request, "Restore", fields, multipart=True,
            message=f"Restore failed: {exc}",
        )

    note = " (corruption was detected and healed)" if result.healed else ""
    return _render(
        request, "Restore", fields, multipart=True,
        message=(
            f"Restored {result.records_loaded} records and "
            f"{result.files_written} files{note}."
        ),
        message_kind="ok",
    )
