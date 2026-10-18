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
