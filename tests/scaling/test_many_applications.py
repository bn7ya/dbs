import threading
import time
from datetime import timedelta
from uuid import UUID

import pytest
from django.db import close_old_connections, connection
from django.utils import timezone

from dbs import audit
from dbs.manager.backups.locks import TakeLock
from dbs.manager.backups.models import BackupPlan
from dbs.manager.backups.services import backup_schedule_service
from dbs.manager.backups.services.backup_run_service import BackupRunService
from dbs.manager.runner import get_runner
from dbs.models import AuditEvent
from tests.manager.factories import make_application, make_server

APPLICATIONS = 200
DISPATCHERS = 2

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def fleet(admin):
    server = make_server(admin)
    due = timezone.now() - timedelta(seconds=30)
    plans = []
    for number in range(APPLICATIONS):
        application = make_application(admin, f"app-{number:03d}", server=server)
        plans.append(
            BackupPlan.objects.create(
                application=application,
                name="hourly",
                kind=BackupPlan.Kind.DBS,
                interval_minutes=60,
                next_run_at=due,
                created_by=admin,
            )
        )
    return plans


@pytest.fixture
def recorded(monkeypatch, settings):
    settings.DBS_MANAGER_JOBS_INLINE = False
    state = {"ran": [], "running": set(), "overlapping": [], "lock": threading.Lock()}

    def run_plan(self, activity_id, plan_id):
        job = self.jobs.start(activity_id)
        subject = job.subject
        with state["lock"]:
            if subject in state["running"]:
                state["overlapping"].append(subject)
            state["running"].add(subject)
        time.sleep(0.002)
        with state["lock"]:
            state["running"].discard(subject)
            state["ran"].append(plan_id)
        self.jobs.succeed(activity_id, {"plan": str(plan_id)})
        self.locks.release(UUID(subject), job.pk)

    monkeypatch.setattr(BackupRunService, "run_plan", run_plan)
    yield state
    get_runner().shutdown(wait=True)


def dispatch():
    close_old_connections()
    try:
        backup_schedule_service.dispatch_due_plans()
    finally:
        connection.close()


def test_two_hundred_plans_due_in_the_same_minute_each_run_once(fleet, recorded):
    started = time.monotonic()
    dispatchers = [threading.Thread(target=dispatch) for _ in range(DISPATCHERS)]
    for thread in dispatchers:
        thread.start()
    for thread in dispatchers:
        thread.join(120)
    get_runner().shutdown(wait=True)
    seconds = time.monotonic() - started

    assert sorted(map(str, recorded["ran"])) == sorted(str(plan.pk) for plan in fleet)
    assert recorded["overlapping"] == []
    runs = AuditEvent.objects.filter(action="backup.run")
    assert runs.count() == APPLICATIONS
    assert set(runs.values_list("status", flat=True)) == {audit.SUCCEEDED}
    later = timezone.now()
    assert all(plan.next_run_at > later for plan in BackupPlan.objects.all())
    assert all(TakeLock().holder(plan.application_id) is None for plan in fleet)
    print(f"\n{APPLICATIONS} plans dispatched and run in {seconds:.1f}s")
