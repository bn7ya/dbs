from __future__ import annotations

import logging
import os
import tempfile
import threading
from contextlib import contextmanager

from django.db import connections
from django.utils import timezone

from . import audit, leases
from .exceptions import ConfigurationError, DBSError

logger = logging.getLogger("dbs")

RUNNER_LEASE = "dbs.runner"
JOB_LEASE_PREFIX = "dbs.job:"
LEASE_SECONDS = 120
HEARTBEAT_SECONDS = 30
DETAIL_MAX = 4000
BACKUP = "backup.create"
RESTORE = "backup.restore"
PANEL_ACTIONS = (BACKUP, RESTORE)
UPLOAD_PREFIX = ".restore-upload.dbs."

class Busy(DBSError):
    code = "busy"


def job_lease(event_id):
    return f"{JOB_LEASE_PREFIX}{event_id}"


class Runner:
    def __init__(self):
        self.owner = leases.unique_owner()
        self.held = False

    @classmethod
    def adopt(cls, owner):
        runner = cls()
        runner.owner = owner
        runner.held = True
        return runner

    def take(self):
        recover()
        if not leases.acquire(RUNNER_LEASE, self.owner, LEASE_SECONDS):
            raise Busy("Another backup or restore is running; try again when it finishes.")
        self.held = True
        return self

    def release(self):
        if not self.held:
            return
        self.held = False
        leases.release(RUNNER_LEASE, self.owner)


class Job:
    def __init__(self, event, owner, hold=()):
        self.event_id = event.pk
        self.data = dict(event.data or {})
        self.owner = owner
        self.lease = job_lease(event.pk)
        self.held = [self.lease, *hold]

    @classmethod
    def adopt(cls, event_id, owner, hold=()):
        from .models import AuditEvent

        return cls(AuditEvent.objects.get(pk=event_id), owner, hold)

    @classmethod
    def begin(cls, action, *, target, data, owner, hold=(), actor=None, remote_addr=""):
        event = audit.record(
            action,
            actor=actor,
            target=target,
            data=data,
            status=audit.RUNNING,
            remote_addr=remote_addr,
        )
        leases.acquire(job_lease(event.pk), owner, LEASE_SECONDS)
        return cls(event, owner, hold)

    def heartbeat(self):
        return leases.Heartbeat(self.held, self.owner, LEASE_SECONDS, HEARTBEAT_SECONDS)

    def succeed(self):
        audit.finish(self.event_id, data=self.data)

    def fail(self, exc):
        audit.fail(
            self.event_id,
            audit.error_code_for(exc),
            data=self.data,
            detail=str(exc)[:DETAIL_MAX] or type(exc).__name__,
        )

    def close(self):
        leases.drop(self.lease, self.owner)

    @contextmanager
    def tracked(self):
        try:
            with self.heartbeat():
                yield self
        except BaseException as exc:
            self.fail(exc)
            raise
        else:
            self.succeed()
        finally:
            self.close()


def refused(action, exc, *, target, data, actor=None, remote_addr=""):
    return audit.record(
        action,
        actor=actor,
        target=target,
        data=data,
        status=audit.FAILED,
        error_code=audit.error_code_for(exc),
        detail=str(exc)[:DETAIL_MAX] or type(exc).__name__,
        remote_addr=remote_addr,
    )


def recover(now=None):
    from .models import Lease

    now = now or timezone.now()
    expired = list(
        Lease.objects.filter(
            name__startswith=JOB_LEASE_PREFIX, expires_at__lte=now
        ).values_list("name", flat=True)
    )
    if not expired:
        return 0
    events = [
        int(name[len(JOB_LEASE_PREFIX):])
        for name in expired
        if name[len(JOB_LEASE_PREFIX):].isdigit()
    ]
    interrupted = audit.interrupt(events=events) if events else 0
    Lease.objects.filter(name__in=expired, expires_at__lte=now).delete()
    if interrupted:
        logger.warning("%d DBS job(s) stopped before they finished", interrupted)
    return interrupted


def launch(work, name="dbs-job"):
    def run():
        try:
            work()
        except Exception:
            logger.exception("a DBS job failed")
        finally:
            connections.close_all()

    thread = threading.Thread(target=run, name=name, daemon=True)
    thread.start()
    return thread


def start_backup(*, database, passphrase="", note="", actor=None, remote_addr=""):
    from .naming import backup_stem
    from .schedule_runner import (
        backup_directory,
        backup_prefix_setting,
        discard_reservation,
        reserve,
    )

    directory = backup_directory()
    if not directory:
        raise ConfigurationError(
            "Set DBS_BACKUP_DIR so the panel has a folder to write backups to."
        )
    runner = Runner().take()
    output = None
    try:
        stem = backup_stem(backup_prefix_setting(), database)
        try:
            os.makedirs(directory, exist_ok=True)
            name = reserve(directory, stem)
        except OSError as exc:
            runner.release()
            return refused(
                BACKUP,
                exc,
                target=directory,
                data=audit.with_actor({"database": database}, actor),
                actor=actor,
                remote_addr=remote_addr,
            ).pk
        output = os.path.join(directory, name)
        job = Job.begin(
            BACKUP,
            target=name,
            data=audit.with_actor({"file": name, "database": database}, actor),
            owner=runner.owner,
            hold=(RUNNER_LEASE,),
            actor=actor,
            remote_addr=remote_addr,
        )
    except BaseException:
        if output is not None:
            discard_reservation(output)
        runner.release()
        raise
    _start(
        job,
        runner,
        lambda: _take_backup(job, runner, output, stem, database, passphrase, note, actor),
        cleanup=lambda: discard_reservation(output),
        spec={
            "kind": "backup",
            "output": output,
            "outputs": [output],
            "stem": stem,
            "database": database,
            "passphrase": passphrase,
            "note": note,
            "actor": getattr(actor, "pk", None),
        },
    )
    return job.event_id


def start_restore(
    *, path, name, passphrase="", dry_run=True, flush=False, owned=False, actor=None,
    remote_addr="",
):
    try:
        runner = Runner().take()
    except BaseException:
        if owned:
            _remove(path)
        raise
    try:
        job = Job.begin(
            RESTORE,
            target=name,
            data=audit.with_actor({"file": name, "dry_run": dry_run, "flushed": flush}, actor),
            owner=runner.owner,
            hold=(RUNNER_LEASE,),
            actor=actor,
            remote_addr=remote_addr,
        )
    except BaseException:
        runner.release()
        if owned:
            _remove(path)
        raise
    _start(
        job,
        runner,
        lambda: _restore(job, runner, path, passphrase, dry_run, flush, owned),
        cleanup=(lambda: _remove(path)) if owned else None,
        spec={
            "kind": "restore",
            "path": path,
            "passphrase": passphrase,
            "dry_run": dry_run,
            "flush": flush,
            "owned": owned,
        },
    )
    return job.event_id


def _start(job, runner, work, cleanup=None, spec=None):
    from . import job_process

    try:
        if spec is not None and job_process.isolated():
            child = job_process.Child(
                job_process.spec_for(
                    event_id=job.event_id, lease=job.lease, owner=runner.owner, **spec
                )
            )
            job_process.supervise(child, outputs=spec.get("outputs", ()), cleanup=cleanup)
        else:
            launch(work)
    except BaseException as exc:
        job.fail(exc)
        job.close()
        if cleanup is not None:
            cleanup()
        runner.release()
        raise


def _take_backup(job, runner, output, stem, database, passphrase, note, actor):
    from .keys import default_passphrase
    from .models import BackupSchedule
    from .schedule_runner import discard_reservation, keep_newest, write_reserved

    try:
        with job.tracked():
            summary = write_reserved(output, passphrase or default_passphrase(), using=database)
            job.data.update(
                size=summary.bytes_written,
                sha256=summary.sha256,
                verified=True,
                compressed=True,
            )
            audit.record_backup(
                output,
                summary.bytes_written,
                summary.sha256,
                database,
                created_by=actor,
                note=note,
            )
        keep = BackupSchedule.seed_keep(BackupSchedule.load().keep)
        keep_newest(os.path.dirname(output), stem, keep)
    except DBSError:
        return
    finally:
        discard_reservation(output)
        runner.release()


def _restore(job, runner, path, passphrase, dry_run, flush, owned):
    from .engine import restore_backup
    from .io import file_digest
    from .keys import with_passphrase

    try:
        with job.tracked():
            size, digest = file_digest(path)
            job.data.update(size=size, sha256=digest)
            result = with_passphrase(
                lambda secret: restore_backup(path, secret, dry_run=dry_run, flush=flush),
                passphrase or None,
            )
            job.data.update(restore_outcome(result, dry_run))
    except DBSError:
        return
    finally:
        if owned:
            _remove(path)
        runner.release()


def restore_outcome(result, dry_run):
    if dry_run:
        return {
            "records": result.records_would_load,
            "files": result.files_would_write,
            "healed": bool(result.healed),
        }
    return {
        "records": result.records_loaded,
        "files": result.files_written,
        "healed": bool(result.healed),
    }


def keep_upload(upload, directory=None):
    if directory:
        os.makedirs(directory, exist_ok=True)
    descriptor, path = tempfile.mkstemp(prefix=UPLOAD_PREFIX, dir=directory or None)
    try:
        with os.fdopen(descriptor, "wb") as fh:
            for chunk in upload.chunks():
                fh.write(chunk)
    except BaseException:
        _remove(path)
        raise
    return path


def _remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


def describe(event):
    data = event.data or {}
    if event.status in audit.UNFINISHED:
        verb = "Backing up to" if event.action == BACKUP else "Restoring"
        return f"{verb} {event.target_name}…"
    if event.status == audit.FAILED:
        verb = "Backup" if event.action == BACKUP else "Restore"
        if event.error_code == audit.INTERRUPTED:
            return f"{verb} stopped before it finished: the process running it ended."
        return f"{verb} failed: {event.detail or event.error_code}"
    if event.action == BACKUP:
        return f"Wrote {event.target_name} ({data.get('size', 0):,} bytes), verified."
    if data.get("dry_run"):
        return (
            f"Dry run: {data.get('records', 0)} records and {data.get('files', 0)} files "
            "would be restored; nothing changed."
        )
    healed = " Corruption was detected and repaired." if data.get("healed") else ""
    return (
        f"Restored {data.get('records', 0)} records and {data.get('files', 0)} files.{healed}"
    )
