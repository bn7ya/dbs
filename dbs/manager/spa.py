from __future__ import annotations

import re
from pathlib import Path

from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.static import serve

BUNDLE = Path(__file__).resolve().parent / "static" / "dbs_manager"
INDEX = "index.html"
HASHED = re.compile(r"[.-][A-Za-z0-9]{8,}\.[A-Za-z0-9]+$")
IMMUTABLE = "public, max-age=31536000, immutable"
REVALIDATE = "no-cache"
BUILD_SCRIPT = "scripts/build_manager_ui.sh"


def bundle_dir():
    return BUNDLE


def asset(request, path):
    response = serve(request, path, document_root=str(bundle_dir()))
    response["Cache-Control"] = IMMUTABLE if HASHED.search(path) else REVALIDATE
    return response


@ensure_csrf_cookie
def index(request, path=""):
    page = bundle_dir() / INDEX
    if page.is_file():
        response = HttpResponse(
            page.read_bytes(), content_type="text/html; charset=utf-8"
        )
    else:
        response = render(
            request,
            "dbs_manager/missing_ui.html",
            {"build_script": BUILD_SCRIPT, "bundle": str(bundle_dir())},
        )
    response["Cache-Control"] = REVALIDATE
    return response


def api_not_found(request, path=""):
    return JsonResponse(
        {"error": {"code": "not_found", "message": "There is no such endpoint."}},
        status=404,
    )
