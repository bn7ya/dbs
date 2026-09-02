from __future__ import annotations

from functools import wraps

from django.http import Http404


def superuser_required(view):
    @wraps(view)
    def guarded(request, *args, **kwargs):
        user = getattr(request, "user", None)
        if user is None or not user.is_active or not user.is_superuser:
            raise Http404
        return view(request, *args, **kwargs)

    return guarded
