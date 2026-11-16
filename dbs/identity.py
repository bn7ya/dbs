from __future__ import annotations

import os

from django.apps import apps

from .conf import setting

SETTING = "DBS_APPLICATION"
HEADER_KEY = "application"
OWN_APP = "dbs"
DJANGO_PACKAGE = "django."
NAMED_MODELS = 5
SHARED_NAMES = frozenset(
    {
        "api",
        "app",
        "application",
        "backend",
        "base",
        "conf",
        "config",
        "core",
        "main",
        "mysite",
        "project",
        "server",
        "settings",
        "site",
        "src",
        "urls",
        "web",
        "website",
    }
)


def application_name() -> str:
    configured = setting(SETTING, None)
    if configured:
        return str(configured)
    named = (
        setting("ROOT_URLCONF", None),
        setting("SETTINGS_MODULE", None),
        os.environ.get("DJANGO_SETTINGS_MODULE"),
    )
    for dotted in named:
        if isinstance(dotted, str) and dotted:
            return dotted.split(".", 1)[0]
    return ""


def is_named_by_setting() -> bool:
    return bool(setting(SETTING, None))


def recorded_application(header: dict) -> str:
    recorded = header.get(HEADER_KEY)
    return recorded if isinstance(recorded, str) else ""


def ships_with_django_or_dbs(app_label: str) -> bool:
    if app_label == OWN_APP:
        return True
    try:
        config = apps.get_app_config(app_label)
    except LookupError:
        return False
    return config.name.startswith(DJANGO_PACKAGE)


def own_labels(labels) -> list[str]:
    return [
        label
        for label in labels
        if isinstance(label, str) and not ships_with_django_or_dbs(label.split(".", 1)[0])
    ]


def is_known(label: str) -> bool:
    try:
        apps.get_model(label)
    except (LookupError, ValueError):
        return False
    return True


def foreign_reason(header: dict, labels) -> str:
    recorded = recorded_application(header)
    if not recorded:
        return ""
    here = application_name()
    if here and recorded != here:
        return (
            f"This backup belongs to the application {recorded!r}, and this project is "
            f"{here!r}."
        )
    own = own_labels(labels)
    if own and not any(is_known(label) for label in own):
        named = ", ".join(own[:NAMED_MODELS])
        more = f" and {len(own) - NAMED_MODELS} more" if len(own) > NAMED_MODELS else ""
        return (
            f"This backup is named {recorded!r} like this project, but this project has "
            f"none of the models it holds ({named}{more})."
        )
    return ""
