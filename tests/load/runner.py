from __future__ import annotations

import http.client
import json
import os
import random
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

PASSPHRASE = "load-test-passphrase"
MIX = (("list", 60), ("detail", 25), ("create", 10), ("update", 5))
SEED_BATCH = 5000
SAMPLE_SECONDS = 1.0
WATCH_SECONDS = 0.2
MEBIBYTE_KB = 1024


@dataclass
class Config:
    folder: Path
    rows: int = 200_000
    customers: int = 10_000
    clients: int = 8
    threads: int = 8
    baseline: float = 60.0
    after: float = 60.0
    during_limit: float = 1800.0
    p95_factor: float = 2.0
    p95_floor_ms: float = 25.0
    rss_growth: float = 0.10


@dataclass
class Phase:
    name: str
    started: float = 0.0
    ended: float = 0.0
    samples: list[tuple[str, float, int]] = field(default_factory=list)
    rss: list[float] = field(default_factory=list)


class Recorder:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.phase = Phase("warmup")

    def record(self, kind: str, seconds: float, status: int) -> None:
        with self.lock:
            self.phase.samples.append((kind, seconds, status))

    def begin(self, name: str) -> Phase:
        with self.lock:
            self.phase.ended = time.monotonic()
            self.phase = Phase(name, started=time.monotonic())
            return self.phase


def memory_mb(pid: Any = "self", field_name: str = "VmRSS") -> float:
    try:
        with open(f"/proc/{pid}/status", encoding="ascii") as status:
            for line in status:
                if line.startswith(field_name + ":"):
                    return int(line.split()[1]) / MEBIBYTE_KB
    except OSError:
        return 0.0
    return 0.0


class PeakWatcher(threading.Thread):
    def __init__(self, pid: int) -> None:
        super().__init__(daemon=True)
        self.pid = pid
        self.peak = 0.0
        self.stopped = threading.Event()

    def run(self) -> None:
        while not self.stopped.wait(WATCH_SECONDS):
            found = memory_mb(self.pid, "VmHWM")
            if not found and not os.path.exists(f"/proc/{self.pid}"):
                return
            self.peak = max(self.peak, found)

    def stop(self) -> float:
        self.stopped.set()
        self.join(5)
        return round(self.peak, 1)


def seed(config: Config) -> None:
    from tests.load.loadapp.models import Customer, Order

    Customer.objects.bulk_create(
        Customer(name=f"customer {index}") for index in range(config.customers)
    )
    first = Customer.objects.order_by("pk").values_list("pk", flat=True).first()
    made = 0
    while made < config.rows:
        count = min(SEED_BATCH, config.rows - made)
        Order.objects.bulk_create(
            Order(
                customer_id=first + (made + offset) % config.customers,
                amount=Decimal(made + offset) / 100,
                note="" if (made + offset) % 4 else f"note {made + offset}",
            )
            for offset in range(count)
        )
        made += count


def serve(threads: int):
    from django.core.wsgi import get_wsgi_application
    from waitress import create_server

    server = create_server(
        get_wsgi_application(), host="127.0.0.1", port=0, threads=threads
    )
    thread = threading.Thread(target=server.run, name="load-web", daemon=True)
    thread.start()
    return server, thread


def client(port: int, recorder: Recorder, stop: threading.Event, number: int, rows: int) -> None:
    rng = random.Random(number)
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
    kinds = [kind for kind, _ in MIX]
    weights = [weight for _, weight in MIX]
    while not stop.is_set():
        kind = rng.choices(kinds, weights)[0]
        method, path, body = "GET", f"/orders/?page={rng.randint(1, 50)}", None
        if kind == "detail":
            path = f"/orders/{rng.randint(1, rows)}/"
        elif kind == "create":
            method, path = "POST", "/orders/"
            body = json.dumps(
                {"amount": "9.99", "note": "load", "new_customer": rng.random() < 0.1}
            )
        elif kind == "update":
            method, path = "POST", f"/orders/{rng.randint(1, rows)}/"
        started = time.perf_counter()
        try:
            connection.request(
                method, path, body=body, headers={"Content-Type": "application/json"}
            )
            response = connection.getresponse()
            response.read()
            status = response.status
        except (OSError, http.client.HTTPException):
            status = 0
            connection.close()
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
        recorder.record(kind, time.perf_counter() - started, status)


def percentile(values: list[float], share: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(share * (len(ordered) - 1))))
    return ordered[index]


def summary(phase: Phase) -> dict[str, Any]:
    seconds = max(phase.ended - phase.started, 0.001)
    latencies = [elapsed * 1000 for _, elapsed, _ in phase.samples]
    failed = [status for _, _, status in phase.samples if status == 0 or status >= 500]
    return {
        "seconds": round(seconds, 1),
        "requests": len(phase.samples),
        "requests_per_second": round(len(phase.samples) / seconds, 1),
        "p50_ms": round(percentile(latencies, 0.50), 1),
        "p95_ms": round(percentile(latencies, 0.95), 1),
        "p99_ms": round(percentile(latencies, 0.99), 1),
        "errors": len(failed),
        "server_errors": sum(1 for status in failed if status >= 500),
        "error_rate": round(len(failed) / max(len(phase.samples), 1), 4),
        "web_rss_mb": round(max(phase.rss, default=0.0), 1),
    }


def sampled(phase: Phase, seconds: float, finished=lambda: False) -> None:
    stop = time.monotonic() + seconds
    while time.monotonic() < stop and not finished():
        phase.rss.append(memory_mb())
        time.sleep(SAMPLE_SECONDS)
    phase.rss.append(memory_mb())


def stream_backup(folder: Path) -> tuple[subprocess.Popen, Path]:
    output = folder / "streamed.dbs"
    kept = folder / "stream-copies"
    kept.mkdir(exist_ok=True)
    environ = {**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)}
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "django",
            "dbs_backup",
            "--stream",
            "--passphrase-stdin",
            "--prefix",
            "loadstream",
            "--output-dir",
            str(kept),
        ],
        stdin=subprocess.PIPE,
        stdout=output.open("wb"),
        stderr=subprocess.PIPE,
        env=environ,
    )
    process.stdin.write(f"{PASSPHRASE}\n".encode())
    process.stdin.close()
    return process, output


def run(config: Config) -> dict[str, Any]:
    from django.core.management import call_command
    from django.db import connection

    from dbs import audit, job_process, jobs, restore_backup, validate_backup
    from dbs.models import AuditEvent
    from dbs.registry import BackupRegistry
    from dbs.schedule_runner import backup_directory
    from tests.load.loadapp.models import Customer, Order

    config.folder.mkdir(parents=True, exist_ok=True)
    seed(config)
    server, web = serve(config.threads)
    port = server.effective_port
    recorder = Recorder()
    stop = threading.Event()
    clients = [
        threading.Thread(
            target=client, args=(port, recorder, stop, number, config.rows), daemon=True
        )
        for number in range(config.clients)
    ]
    for started in clients:
        started.start()
    time.sleep(2)

    before = recorder.begin("before")
    sampled(before, config.baseline)

    during = recorder.begin("during")
    orders_at_start = Order.objects.count()
    children: list[Any] = []
    real_supervise = job_process.supervise

    def watched(child, **kwargs):
        children.append(PeakWatcher(child.pid))
        children[-1].start()
        return real_supervise(child, **kwargs)

    job_process.supervise = watched
    backup_started = time.monotonic()
    try:
        event_id = jobs.start_backup(database="default", passphrase=PASSPHRASE)
    finally:
        job_process.supervise = real_supervise
    process, streamed = stream_backup(config.folder)
    stream_watcher = PeakWatcher(process.pid)
    stream_watcher.start()
    timings: dict[str, float] = {}

    def done() -> bool:
        event = AuditEvent.objects.get(pk=event_id)
        if event.status not in audit.UNFINISHED and "panel" not in timings:
            timings["panel"] = time.monotonic() - backup_started
        if process.poll() is not None and "stream" not in timings:
            timings["stream"] = time.monotonic() - backup_started
        return "panel" in timings and "stream" in timings

    sampled(during, config.during_limit, done)
    process.wait(timeout=60)
    stream_errors = process.stderr.read().decode("utf-8", "replace")
    orders_at_end = Order.objects.count()

    after = recorder.begin("after")
    sampled(after, config.after)
    recorder.begin("done")
    stop.set()
    for finished in clients:
        finished.join(70)
    server.close()
    web.join(5)

    event = AuditEvent.objects.get(pk=event_id)
    panel_path = Path(backup_directory()) / event.data.get("file", event.target_name)
    checks = []
    panel_ok = event.status == audit.SUCCEEDED and panel_path.is_file()
    stream_ok = process.returncode == 0 and streamed.stat().st_size > 0
    checks.append(check("panel backup succeeded", panel_ok, event.error_code or ""))
    checks.append(check("streamed backup succeeded", stream_ok, stream_errors[-300:]))
    validated = {}
    for name, path in (("panel", panel_path), ("stream", streamed)):
        if path.is_file():
            result = validate_backup(str(path), PASSPHRASE)
            validated[name] = result.ok and result.decrypted_ok
        else:
            validated[name] = False
    checks.append(check("both backups validate", all(validated.values()), str(validated)))

    restored = {"customers": 0, "orders": 0, "orphans": -1}
    if panel_ok:
        call_command("migrate", database="restored", run_syncdb=True, verbosity=0)
        registry = BackupRegistry()
        registry.register(Customer)
        registry.register(Order)
        restore_backup(str(panel_path), PASSPHRASE, using="restored", flush=True, registry=registry)
        customers = Customer.objects.using("restored")
        found = Order.objects.using("restored")
        restored = {
            "customers": customers.count(),
            "orders": found.count(),
            "orphans": found.exclude(customer_id__in=customers.values("pk")).count(),
        }
    consistent = (
        restored["orphans"] == 0
        and orders_at_start <= restored["orders"] <= orders_at_end
    )
    checks.append(
        check(
            "the restored snapshot is consistent",
            consistent,
            f"{restored} between {orders_at_start} and {orders_at_end} orders",
        )
    )

    phases = {phase.name: summary(phase) for phase in (before, during, after)}
    allowed_p95 = max(
        config.p95_factor * phases["before"]["p95_ms"],
        phases["before"]["p95_ms"] + config.p95_floor_ms,
    )
    checks.append(
        check(
            "no server error while backing up",
            phases["during"]["server_errors"] == 0,
            f"{phases['during']['server_errors']} server errors",
        )
    )
    checks.append(
        check(
            "p95 latency within its bound while backing up",
            phases["during"]["p95_ms"] <= allowed_p95,
            f"{phases['during']['p95_ms']} ms against at most {allowed_p95:.1f} ms",
        )
    )
    allowed_rss = phases["before"]["web_rss_mb"] * (1 + config.rss_growth)
    checks.append(
        check(
            "web process memory stays flat",
            phases["during"]["web_rss_mb"] <= allowed_rss,
            f"{phases['during']['web_rss_mb']} MiB against at most {allowed_rss:.1f} MiB",
        )
    )
    return {
        "database": connection.vendor,
        "config": {key: str(value) for key, value in asdict(config).items()},
        "phases": phases,
        "backups": {
            "panel": {
                "seconds": round(timings.get("panel", 0.0), 1),
                "bytes": panel_path.stat().st_size if panel_path.is_file() else 0,
                "peak_rss_mb": children[0].stop() if children else 0.0,
                "status": event.status,
            },
            "stream": {
                "seconds": round(timings.get("stream", 0.0), 1),
                "bytes": streamed.stat().st_size if streamed.is_file() else 0,
                "peak_rss_mb": stream_watcher.stop(),
                "exit_status": process.returncode,
            },
        },
        "restored": restored,
        "checks": checks,
        "passed": all(item["passed"] for item in checks),
    }


def check(name: str, passed: bool, detail: str) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "detail": detail}


def markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Backup under load",
        "",
        f"Database: {report['database']}. Rows: {report['config']['rows']}. "
        f"Clients: {report['config']['clients']}. Web threads: {report['config']['threads']}.",
        "",
        "| Phase | Requests/s | p50 ms | p95 ms | p99 ms | Errors | 5xx | Web RSS MiB |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, phase in report["phases"].items():
        lines.append(
            f"| {name} | {phase['requests_per_second']} | {phase['p50_ms']} | "
            f"{phase['p95_ms']} | {phase['p99_ms']} | {phase['errors']} | "
            f"{phase['server_errors']} | {phase['web_rss_mb']} |"
        )
    lines += [
        "",
        "| Backup | Seconds | Bytes | Peak RSS MiB |",
        "|---|---:|---:|---:|",
    ]
    for name, backup in report["backups"].items():
        lines.append(
            f"| {name} | {backup['seconds']} | {backup['bytes']:,} | {backup['peak_rss_mb']} |"
        )
    lines += ["", "| Check | Result | Detail |", "|---|---|---|"]
    for item in report["checks"]:
        result = "passed" if item["passed"] else "FAILED"
        detail = str(item["detail"]).replace("|", "/").replace("\n", " ")
        lines.append(f"| {item['name']} | {result} | {detail} |")
    lines.append("")
    return "\n".join(lines)


def write_report(report: dict[str, Any], folder: Path) -> tuple[Path, Path]:
    folder.mkdir(parents=True, exist_ok=True)
    written = folder / "load-report.md"
    data = folder / "load-report.json"
    written.write_text(markdown(report), encoding="utf-8")
    data.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return written, data
