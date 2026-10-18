import json
import os
import sys
import time

PASSPHRASE = "isolation-pass-phrase"
BARRIER = "DBS_INSTANCE_BARRIER"
LEASE = "DBS_INSTANCE_LEASE_SECONDS"
BOOTSTRAP = "DBS_INSTANCE_BOOTSTRAP"
WAIT_SECONDS = 120


def wait_for_barrier():
    barrier = os.environ.get(BARRIER, "")
    stop = time.monotonic() + WAIT_SECONDS
    while barrier and not os.path.exists(barrier) and time.monotonic() < stop:
        time.sleep(0.01)


def finished(event_id):
    from dbs import audit
    from dbs.models import AuditEvent

    stop = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < stop:
        event = AuditEvent.objects.get(pk=event_id)
        if event.status not in audit.UNFINISHED:
            return event.status
        time.sleep(0.1)
    return "unfinished"


def main(action):
    import django

    django.setup()
    from django.conf import settings

    from dbs import jobs, schedule_runner

    if os.environ.get(BOOTSTRAP):
        settings.DBS_JOB_BOOTSTRAP = os.environ[BOOTSTRAP]

    if os.environ.get(LEASE):
        jobs.LEASE_SECONDS = int(os.environ[LEASE])
        jobs.HEARTBEAT_SECONDS = max(1, jobs.LEASE_SECONDS // 4)
    print(json.dumps({"ready": os.getpid()}), flush=True)
    wait_for_barrier()
    if action == "scheduled":
        output = schedule_runner.run_due()
        print(json.dumps({"output": output}), flush=True)
        return 0
    try:
        event_id = jobs.start_backup(database="default", passphrase=PASSPHRASE)
    except jobs.Busy:
        print(json.dumps({"busy": True}), flush=True)
        return 0
    print(json.dumps({"event": event_id}), flush=True)
    if action == "hold":
        time.sleep(WAIT_SECONDS)
        return 0
    print(json.dumps({"status": finished(event_id)}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
