from dbs.models import AuditEvent

PASSWORD = "correct-horse-battery-staple"


def logged(action=None):
    entries = AuditEvent.objects.select_related("actor").order_by("-created_at", "-id")
    if action is not None:
        entries = entries.filter(action=action)
    return list(entries)
