from __future__ import annotations

import glob
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import threading
import time

from .conf import setting
from .exceptions import BackupError, ConfigurationError

logger = logging.getLogger("dbs")

TIME_LIMIT = "time_limit"
MEMORY_LIMIT = "memory_limit"
LEASE_LOST = "lease_lost"
KILLED = "killed"
EXIT_CODES = {TIME_LIMIT: 3, MEMORY_LIMIT: 4, LEASE_LOST: 5}
REASONS = {code: reason for reason, code in EXIT_CODES.items()}
DEFAULT_TIME_LIMIT = "6h"
DEFAULT_MEMORY_LIMIT = "2G"
DEFAULT_NICE = 10
WATCH_SECONDS = 1.0
LEASE_WATCH_SECONDS = 10.0
GRACE_SECONDS = 60
PARENT_MEMORY_FACTOR = 1.25
PARENT_STRIKES = 5
STDERR_TAIL = 2000
SIZE = re.compile(r"^\s*(\d+)\s*([kmgt]?)i?b?\s*$", re.IGNORECASE)
MULTIPLIERS = {"": 1, "k": 1024, "m": 1024 ** 2, "g": 1024 ** 3, "t": 1024 ** 4}
PAGE_SIZE = os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else 4096


def parse_size(spec) -> int:
    if isinstance(spec, int):
        return max(spec, 0)
    match = SIZE.match(str(spec))
    if not match:
        raise ConfigurationError(
            f"Cannot read the size {spec!r}; use forms like 512M, 2G or 0 for no limit."
        )
    return int(match.group(1)) * MULTIPLIERS[match.group(2).lower()]


def time_limit() -> int:
    from .scheduling import parse_interval

    return parse_interval(str(setting("DBS_JOB_TIME_LIMIT", DEFAULT_TIME_LIMIT)))


def memory_limit() -> int:
    return parse_size(setting("DBS_JOB_MEMORY_LIMIT", DEFAULT_MEMORY_LIMIT))


def settings_module() -> str:
    from django.conf import settings

    return getattr(settings, "SETTINGS_MODULE", None) or os.environ.get(
        "DJANGO_SETTINGS_MODULE", ""
    )


def isolated() -> bool:
    return bool(setting("DBS_JOB_PROCESS", True)) and bool(settings_module())


def interpreter() -> str:
    from .connection import python_path

    return str(setting("DBS_JOB_PYTHON", "") or python_path())


def child_environment() -> dict:
    paths = [os.getcwd() if entry == "" else entry for entry in sys.path]
    inherited = os.environ.get("PYTHONPATH", "")
    if inherited:
        paths += inherited.split(os.pathsep)
    environment = dict(os.environ)
    environment["DJANGO_SETTINGS_MODULE"] = settings_module()
    environment["PYTHONPATH"] = os.pathsep.join(dict.fromkeys(path for path in paths if path))
    return environment


PROBE = "import django; django.setup(); import dbs"
PROBE_SECONDS = 60


def probe() -> str:
    try:
        result = subprocess.run(
            [interpreter(), "-c", PROBE],
            env=child_environment(),
            cwd=os.getcwd(),
            capture_output=True,
            text=True,
            timeout=PROBE_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return str(exc)
    if result.returncode == 0:
        return ""
    lines = (result.stderr or result.stdout).strip().splitlines()
    return lines[-1] if lines else f"exit status {result.returncode}"


def command() -> list:
    return [interpreter(), "-m", "dbs.job_process"]


def spec_for(*, kind: str, owner: str, **fields) -> dict:
    return {
        "kind": kind,
        "owner": owner,
        "time_limit": time_limit(),
        "memory_limit": memory_limit(),
        "nice": int(setting("DBS_JOB_NICE", DEFAULT_NICE)),
        "bootstrap": str(setting("DBS_JOB_BOOTSTRAP", "") or ""),
        **fields,
    }


class Child:
    def __init__(self, spec: dict, *, capture: bool = False):
        self.spec = spec
        self.strikes = 0
        self.stderr = tempfile.TemporaryFile()
        self.process = subprocess.Popen(
            command(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
            stderr=self.stderr,
            env=child_environment(),
            cwd=os.getcwd(),
            start_new_session=True,
        )
        stdin, self.process.stdin = self.process.stdin, None
        try:
            stdin.write((json.dumps(spec) + "\n").encode("utf-8"))
        except OSError:
            pass
        finally:
            try:
                stdin.close()
            except OSError:
                pass

    @property
    def pid(self) -> int:
        return self.process.pid

    def wait(self) -> tuple[int, bytes]:
        deadline = time.monotonic() + self.spec["time_limit"] + GRACE_SECONDS
        output = b""
        while True:
            if self.process.stdout is not None:
                try:
                    output, _ = self.process.communicate(timeout=WATCH_SECONDS)
                except subprocess.TimeoutExpired:
                    pass
            else:
                try:
                    self.process.wait(timeout=WATCH_SECONDS)
                except subprocess.TimeoutExpired:
                    pass
            if self.process.returncode is not None:
                return self.process.returncode, output
            if time.monotonic() > deadline or self._over_memory():
                self.process.kill()

    def _over_memory(self) -> bool:
        limit = self.spec["memory_limit"]
        if not limit:
            return False
        resident = resident_bytes(self.process.pid)
        over = resident is not None and resident > limit * PARENT_MEMORY_FACTOR
        self.strikes = self.strikes + 1 if over else 0
        return self.strikes >= PARENT_STRIKES

    def tail(self) -> str:
        try:
            self.stderr.seek(0, os.SEEK_END)
            size = self.stderr.tell()
            self.stderr.seek(max(size - STDERR_TAIL, 0))
            return self.stderr.read().decode("utf-8", "replace").strip()
        except (OSError, ValueError):
            return ""
        finally:
            self.stderr.close()


def resident_bytes(pid: int | str = "self") -> int | None:
    try:
        with open(f"/proc/{pid}/statm", encoding="ascii") as fh:
            return int(fh.read().split()[1]) * PAGE_SIZE
    except (OSError, ValueError, IndexError):
        pass
    if pid != "self":
        return None
    try:
        import resource
    except ImportError:
        return None
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak if sys.platform == "darwin" else peak * 1024


def reason_of(returncode: int) -> str:
    return REASONS.get(returncode, KILLED)


def settle(owner: str, returncode: int, detail: str, *, outputs=()) -> None:
    from . import audit, leases
    from .jobs import JOB_LEASE_PREFIX, RUNNER_LEASE
    from .models import Lease

    if returncode != 0:
        reason = reason_of(returncode)
        held = Lease.objects.filter(owner=owner, name__startswith=JOB_LEASE_PREFIX)
        for name in held.values_list("name", flat=True):
            event_id = name[len(JOB_LEASE_PREFIX):]
            if event_id.isdigit():
                audit.fail(
                    int(event_id),
                    reason,
                    detail=_explained(reason, returncode, detail),
                )
        for output in outputs:
            remove_partials(output)
    Lease.objects.filter(owner=owner, name__startswith=JOB_LEASE_PREFIX).delete()
    leases.release(RUNNER_LEASE, owner)


def _explained(reason: str, returncode: int, detail: str) -> str:
    if reason == TIME_LIMIT:
        return "The job ran longer than DBS_JOB_TIME_LIMIT and was stopped."
    if reason == MEMORY_LIMIT:
        return "The job used more memory than DBS_JOB_MEMORY_LIMIT and was stopped."
    if reason == LEASE_LOST:
        return "Another process took this job over, so this one stopped."
    ended = f"The process running the job ended with status {returncode}."
    return f"{ended} {detail}".strip()


def remove_partials(output: str) -> None:
    from .schedule_runner import discard_reservation

    directory, name = os.path.split(output)
    for partial in glob.glob(os.path.join(glob.escape(directory), f".{glob.escape(name)}.*.partial")):
        try:
            os.remove(partial)
        except FileNotFoundError:
            continue
        except OSError as exc:
            logger.warning("could not remove the partial file %s: %s", partial, exc)
    discard_reservation(output)


def supervise(child: Child, *, outputs=(), cleanup=None) -> threading.Thread:
    def watch():
        from django.db import connections

        try:
            returncode, _output = child.wait()
            settle(child.spec["owner"], returncode, child.tail(), outputs=outputs)
            if cleanup is not None:
                cleanup()
        except Exception:
            logger.exception("could not settle a DBS job process")
        finally:
            connections.close_all()

    thread = threading.Thread(target=watch, name="dbs-job-supervisor", daemon=True)
    thread.start()
    return thread


def run_and_wait(spec: dict, *, outputs=()) -> dict:
    child = Child(spec, capture=True)
    returncode, output = child.wait()
    detail = child.tail()
    settle(spec["owner"], returncode, detail, outputs=outputs)
    result = _last_json(output)
    if returncode != 0 and "error" not in result:
        raise BackupError(_explained(reason_of(returncode), returncode, detail))
    if "error" in result:
        raise BackupError(result["error"])
    return result


def _last_json(output: bytes) -> dict:
    for line in reversed(output.decode("utf-8", "replace").splitlines()):
        try:
            found = json.loads(line)
        except ValueError:
            continue
        if isinstance(found, dict):
            return found
    return {}


class Limits:
    def __init__(self, spec: dict, on_breach):
        self.seconds = spec["time_limit"]
        self.memory = spec["memory_limit"]
        self.owner = spec["owner"]
        self.lease = spec.get("lease", "")
        self.on_breach = on_breach
        self.started = time.monotonic()
        self._stopped = threading.Event()
        self._thread = threading.Thread(target=self._watch, name="dbs-job-limits", daemon=True)

    def __enter__(self) -> "Limits":
        self._thread.start()
        return self

    def __exit__(self, *exc_info) -> None:
        self._stopped.set()
        self._thread.join()

    def _watch(self) -> None:
        checked = time.monotonic()
        while not self._stopped.wait(WATCH_SECONDS):
            reason = self.breached()
            if reason is None and self.lease and time.monotonic() - checked > LEASE_WATCH_SECONDS:
                checked = time.monotonic()
                reason = self._lease_lost()
            if reason is not None:
                self.on_breach(reason)
                return

    def breached(self) -> str | None:
        if time.monotonic() - self.started > self.seconds:
            return TIME_LIMIT
        if self.memory:
            resident = resident_bytes()
            if resident is not None and resident > self.memory:
                return MEMORY_LIMIT
        return None

    def _lease_lost(self) -> str | None:
        from django.db import DatabaseError, connections

        from . import leases

        try:
            held = leases.holder(self.lease)
        except DatabaseError:
            return None
        finally:
            connections.close_all()
        return LEASE_LOST if held is None or held.owner != self.owner else None


def _breach(spec: dict, reason: str) -> None:
    from . import audit
    from .jobs import JOB_LEASE_PREFIX
    from .models import Lease

    try:
        for name in Lease.objects.filter(
            owner=spec["owner"], name__startswith=JOB_LEASE_PREFIX
        ).values_list("name", flat=True):
            event_id = name[len(JOB_LEASE_PREFIX):]
            if event_id.isdigit() and reason != LEASE_LOST:
                audit.fail(int(event_id), reason, detail=_explained(reason, 0, ""))
        for output in spec.get("outputs", ()):
            remove_partials(output)
    finally:
        sys.stderr.flush()
        os._exit(EXIT_CODES[reason])


def _bootstrap(path: str) -> None:
    if path:
        from django.utils.module_loading import import_string

        import_string(path)()
        return
    import django

    django.setup()


def _lower_priority(niceness: int) -> None:
    if niceness > 0 and hasattr(os, "nice"):
        try:
            os.nice(niceness)
        except OSError:
            pass


def run(spec: dict) -> dict:
    from . import jobs, schedule_runner
    from .exceptions import DBSError

    kind = spec["kind"]
    runner = jobs.Runner.adopt(spec["owner"])
    if kind == "scheduled":
        from django.utils.dateparse import parse_datetime

        from .models import BackupSchedule

        try:
            output = schedule_runner._run(
                BackupSchedule.load(), runner, parse_datetime(spec["now"])
            )
        except DBSError as exc:
            return {"error": str(exc), "type": type(exc).__name__}
        return {"output": output}
    job = jobs.Job.adopt(spec["event_id"], spec["owner"], hold=(jobs.RUNNER_LEASE,))
    if kind == "backup":
        jobs._take_backup(
            job,
            runner,
            spec["output"],
            spec["stem"],
            spec["database"],
            spec.get("passphrase", ""),
            spec.get("note", ""),
            _actor(spec.get("actor")),
        )
    elif kind == "restore":
        jobs._restore(
            job,
            runner,
            spec["path"],
            spec.get("passphrase", ""),
            spec["dry_run"],
            spec["flush"],
            spec["owned"],
        )
    else:
        raise ConfigurationError(f"Unknown DBS job kind {kind!r}.")
    return {"event_id": spec["event_id"]}


def _actor(actor_id):
    if actor_id is None:
        return None
    from django.contrib.auth import get_user_model

    return get_user_model()._default_manager.filter(pk=actor_id).first()


def main(stream=None) -> int:
    spec = json.loads((stream or sys.stdin).readline())
    _lower_priority(int(spec.get("nice", 0)))
    _bootstrap(spec.get("bootstrap", ""))
    with Limits(spec, lambda reason: _breach(spec, reason)):
        result = run(spec)
    sys.stdout.write(json.dumps(result) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
