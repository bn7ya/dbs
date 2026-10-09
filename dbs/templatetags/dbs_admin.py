from __future__ import annotations

from django import template
from django.urls import reverse

from ..conf import setting
from ..health import report
from ..models import AnomalyEvent, BackupRecord, BackupSchedule, BackupTarget, SecurityPolicy
from ..security import geo

register = template.Library()


@register.simple_tag
def dbs_dashboard_url():
    return reverse("admin:app_list", kwargs={"app_label": "dbs"})


@register.inclusion_tag("admin/dbs/_dashboard.html")
def dbs_dashboard():
    return {
        "targets": BackupTarget.objects.all(),
        "settings_targets": sorted((setting("DBS_SSH_TARGETS", {}) or {}).items()),
        "records": BackupRecord.objects.select_related("target")[:10],
        "anomalies": AnomalyEvent.objects.select_related("user")[:5],
        "policy": SecurityPolicy.load(),
        "schedule": BackupSchedule.load(),
        "health": report(),
        "geolocation": geo.enabled(),
    }
