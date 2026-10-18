import hashlib
import os

import pytest
from django.db.models import Q

from dbs import audit, jobs, schedule_runner
from dbs.exceptions import BackupError
from dbs.models import AuditEvent, BackupRecord, BackupSchedule, Lease
from tests.isolation.test_job_process import PASS, backup_dir, children, finished  # noqa: F401
from tests.testapp.models import Author

pytestmark = pytest.mark.django_db(transaction=True)


def kept(folder):
    found = {}
    for name in os.listdir(folder):
        with open(os.path.join(folder, name), "rb") as handle:
            found[name] = hashlib.sha256(handle.read()).hexdigest()
    return found


def leases_held():
    return Lease.objects.filter(owner__gt="").filter(
        Q(name__startswith=jobs.JOB_LEASE_PREFIX) | Q(name=jobs.RUNNER_LEASE)
    )


@pytest.mark.parametrize(
    "hook, code",
    [
        ("tests.isolation.hooks.full_disk", audit.DISK_FULL),
        ("tests.isolation.hooks.lost_database", audit.DATABASE_FAILED),
        ("tests.isolation.hooks.broken_deflate", audit.UNEXPECTED),
    ],
)
def test_a_backup_that_fails_leaves_the_older_backups_and_the_next_one_works(
    backup_dir, children, settings, hook, code  # noqa: F811
):
    for name in ("Ada", "Grace", "Hedy"):
        Author.objects.create(name=name)
    first = finished(jobs.start_backup(database="default", passphrase=PASS))
    before = kept(backup_dir)

    settings.DBS_JOB_BOOTSTRAP = hook
    failed = finished(jobs.start_backup(database="default", passphrase=PASS))

    assert first.status == audit.SUCCEEDED and len(before) == 1
    assert (failed.status, failed.error_code) == (audit.FAILED, code)
    assert kept(backup_dir) == before
    assert BackupRecord.objects.count() == 1
    assert not leases_held().exists()
    assert len(children) == 2

    settings.DBS_JOB_BOOTSTRAP = ""
    again = finished(jobs.start_backup(database="default", passphrase=PASS))

    assert again.status == audit.SUCCEEDED
    after = kept(backup_dir)
    assert len(after) == 2 and set(before.items()) <= set(after.items())


@pytest.mark.skipif(os.geteuid() == 0, reason="root writes into any folder")
def test_a_backup_folder_that_cannot_be_written_fails_with_its_code(
    backup_dir, children  # noqa: F811
):
    backup_dir.chmod(0o500)
    try:
        failed = finished(jobs.start_backup(database="default", passphrase=PASS))
    finally:
        backup_dir.chmod(0o700)

    assert (failed.status, failed.error_code) == (audit.FAILED, audit.PERMISSION_DENIED)
    assert kept(backup_dir) == {}
    assert not leases_held().exists()


def test_a_scheduled_backup_that_fails_keeps_the_schedule_and_its_older_backups(
    backup_dir, settings  # noqa: F811
):
    BackupSchedule.objects.create(enabled=True, interval="6h")
    Author.objects.create(name="Ada")
    assert schedule_runner.run_due(force=True) is not None
    before = kept(backup_dir)
    settings.DBS_JOB_BOOTSTRAP = "tests.isolation.hooks.full_disk"

    with pytest.raises(BackupError, match="No space left on device"):
        schedule_runner.run_due(force=True)

    schedule = BackupSchedule.load()
    assert schedule.enabled is True and schedule.last_status == audit.FAILED
    assert kept(backup_dir) == before
    failed = AuditEvent.objects.filter(action="backup.create").order_by("-id").first()
    assert (failed.status, failed.error_code) == (audit.FAILED, audit.DISK_FULL)
    assert not leases_held().exists()


FULL_DISK = os.environ.get("DBS_TEST_FULL_DISK", "")


@pytest.mark.skipif(
    not FULL_DISK, reason="Set DBS_TEST_FULL_DISK to a small tmpfs, such as one of 1 MiB."
)
def test_a_backup_that_fills_a_real_disk_fails_with_disk_full_and_leaves_nothing(
    settings, children  # noqa: F811
):
    settings.DBS_BACKUP_DIR = FULL_DISK
    settings.DBS_KDF_TIME_COST = 1
    settings.DBS_KDF_MEMORY_COST = 8192
    Author.objects.bulk_create(
        Author(name=os.urandom(48).hex()) for _ in range(20_000)
    )

    failed = finished(jobs.start_backup(database="default", passphrase=PASS))

    assert (failed.status, failed.error_code) == (audit.FAILED, audit.DISK_FULL)
    assert os.listdir(FULL_DISK) == []
    assert BackupRecord.objects.count() == 0
    assert not leases_held().exists()
