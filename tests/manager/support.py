from dbs.models import AuditEvent

PASSWORD = "correct-horse-battery-staple"


def logged(action=None):
    entries = AuditEvent.objects.select_related("actor").order_by("-created_at", "-id")
    if action is not None:
        entries = entries.filter(action=action)
    return list(entries)


def backdated(entry, **fields):
    AuditEvent.objects.filter(pk=entry.pk).update(**fields)
    return AuditEvent.objects.select_related("actor").get(pk=entry.pk)
