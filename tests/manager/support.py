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


class Logged:
    def __init__(self, event):
        self.event = event

    def __getattr__(self, name):
        return getattr(self.event, name)

    @property
    def server(self):
        from dbs.manager.servers.models import Server

        if not self.event.subject:
            return None
        return Server.all_objects.filter(pk=self.event.subject).first()

    @property
    def detail(self):
        return self.event.data

    @property
    def target(self):
        return self.event.target_name

    @property
    def ip(self):
        return self.event.remote_addr or None


def logged_entries(action=None):
    return [Logged(event) for event in logged(action)]
