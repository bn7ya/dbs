import os
import time

BARRIER = "DBS_TEST_BARRIER"
WAIT_SECONDS = 120


def _waiting(real, before=None):
    def wait_then_write(output, *args, **kwargs):
        if before is not None:
            before()
        barrier = os.environ.get(BARRIER, "")
        stop = time.monotonic() + WAIT_SECONDS
        while barrier and not os.path.exists(barrier) and time.monotonic() < stop:
            time.sleep(0.05)
        return real(output, *args, **kwargs)

    return wait_then_write


def _setup():
    import django

    django.setup()
    from dbs import job_process

    job_process.LEASE_WATCH_SECONDS = 0.5


def slow():
    _setup()
    from dbs import schedule_runner

    schedule_runner.write_reserved = _waiting(schedule_runner.write_reserved)


def hungry():
    _setup()
    from dbs import schedule_runner

    held = []
    schedule_runner.write_reserved = _waiting(
        schedule_runner.write_reserved, lambda: held.append(bytearray(600 * 1024 * 1024))
    )


class FullDisk:
    def __init__(self, handle, room):
        self.handle = handle
        self.room = room

    def write(self, data):
        import errno

        if self.room < len(data):
            raise OSError(errno.ENOSPC, "No space left on device")
        self.room -= len(data)
        return self.handle.write(data)

    def __getattr__(self, name):
        return getattr(self.handle, name)


def full_disk():
    _setup()
    from dbs.engine import backup

    real = backup.write_backup

    def filling(output, *args, **kwargs):
        return real(FullDisk(output, 64 * 1024), *args, **kwargs)

    backup.write_backup = filling


def broken_deflate():
    _setup()
    import zlib

    from dbs.engine import pipeline

    def broken(segment):
        raise zlib.error("deflate failed")

    pipeline._deflate = broken


def lost_database():
    _setup()
    from django.db import OperationalError

    from dbs.engine import backup

    real = backup.serialize_batches
    calls = []

    def dropping(*args, **kwargs):
        calls.append(args[0])
        if len(calls) > 1:
            raise OperationalError("server closed the connection unexpectedly")
        yield from real(*args, **kwargs)

    backup.serialize_batches = dropping
