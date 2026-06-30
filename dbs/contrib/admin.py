"""Staff-only views to download and upload/restore a DBS backup."""

from __future__ import annotations

import datetime

from django.contrib.auth.decorators import user_passes_test
from django.http import HttpResponse
from django.template import RequestContext, Template
from django.views.decorators.http import require_http_methods

from ..engine import create_backup, restore_backup
from ..exceptions import DBSError

_PAGE = """
<!doctype html><html><head><title>DBS {title}</title>
<style>body{{font-family:sans-serif;max-width:640px;margin:3rem auto}}
label{{display:block;margin:.6rem 0 .2rem}} input{{padding:.4rem;width:100%}}
button{{margin-top:1rem;padding:.5rem 1rem}} .msg{{padding:.6rem;border-radius:4px}}
.err{{background:#fde8e8;color:#9b1c1c}} .ok{{background:#e6f4ea;color:#1e6b32}}</style>
</head><body><h1>DBS {title}</h1>{message}
<form method="post" {enctype}>{csrf}{fields}<button type="submit">{title}</button></form>
</body></html>
"""


def _render(request, title, fields, *, enctype="", message=""):
    tmpl = Template(
        _PAGE.format(
            title=title,
            enctype=enctype,
            fields=fields,
            message=message,
            csrf="{% csrf_token %}",
        )
    )
    return HttpResponse(tmpl.render(RequestContext(request)))


def _superuser_required(view):
    # Redirects unauthenticated / non-superusers to settings.LOGIN_URL. We avoid
    # admin's staff_member_required so the views don't require the admin app's
    # URL namespace to be installed.
    return user_passes_test(lambda u: u.is_active and u.is_superuser)(view)


@_superuser_required
@require_http_methods(["GET", "POST"])
def backup_download(request):
    """GET shows a passphrase form; POST streams the encrypted backup file."""
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
            message='<p class="msg err">Passphrases are empty or do not match.</p>',
        )
    try:
        container = create_backup(passphrase)
    except DBSError as exc:
        return _render(request, "Backup", fields, message=f'<p class="msg err">{exc}</p>')

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    response = HttpResponse(container, content_type="application/octet-stream")
    response["Content-Disposition"] = f'attachment; filename="backup-{stamp}.dbs"'
    return response


@_superuser_required
@require_http_methods(["GET", "POST"])
def restore_upload(request):
    """GET shows an upload form; POST restores the uploaded backup."""
    fields = (
        '<label>Backup file (.dbs)</label><input type="file" name="backup" required>'
        '<label>Passphrase</label><input type="password" name="passphrase" required>'
    )
    enctype = 'enctype="multipart/form-data"'
    if request.method == "GET":
        return _render(request, "Restore", fields, enctype=enctype)

    upload = request.FILES.get("backup")
    passphrase = request.POST.get("passphrase", "")
    if not upload or not passphrase:
        return _render(
            request, "Restore", fields, enctype=enctype,
            message='<p class="msg err">A file and passphrase are required.</p>',
        )
    try:
        result = restore_backup(upload.read(), passphrase)
    except DBSError as exc:
        return _render(
            request, "Restore", fields, enctype=enctype,
            message=f'<p class="msg err">Restore failed: {exc}</p>',
        )

    note = " (corruption was detected and healed)" if result.healed else ""
    return _render(
        request, "Restore", fields, enctype=enctype,
        message=(
            f'<p class="msg ok">Restored {result.records_loaded} records and '
            f'{result.files_written} files{note}.</p>'
        ),
    )
