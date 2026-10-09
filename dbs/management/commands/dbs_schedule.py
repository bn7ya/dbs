from __future__ import annotations

import logging
import os
import threading

from django.core.management.base import BaseCommand, CommandError

from dbs._cli import require_env_passphrase
from dbs.conf import setting
from dbs.crypto.kdf import KDFParams
from dbs import schedule_runner
from dbs.exceptions import DBSError
from dbs.naming import DEFAULT_PREFIX
from dbs.scheduling import install_stop_handlers, parse_interval, run_schedule
from dbs.transports.ssh import SSHTarget

logger = logging.getLogger("dbs")

MINIMUM_SENSIBLE_INTERVAL = 60
PLAN_OPTIONS = ("interval", "output_dir", "prefix", "keep", "push", "keep_remote")


def _push_target(name):
    return SSHTarget.from_settings(name) if name else None


class Command(BaseCommand):
    help = "Run backups on a repeating interval, with retention and optional offsite push."

    def add_arguments(self, parser):
        parser.add_argument("--interval", default=None, help="How often to back up: 90s, 30m, 6h, 1d.")
        parser.add_argument("--output-dir", default=None, help="Directory the backups are written to.")
        parser.add_argument("--prefix", default=None, help="Filename prefix for this project.")
        parser.add_argument("--keep", type=int, default=None, help="How many local backups to retain.")
        parser.add_argument("--push", default=None, help="Name of a DBS_SSH_TARGETS entry to also push to.")
        parser.add_argument("--keep-remote", type=int, default=None, help="How many pushed backups to retain.")
        parser.add_argument("--database", default="default", help="Database alias to back up.")
        parser.add_argument("--no-compress", action="store_true", help="Disable zlib compression.")
        parser.add_argument("--no-verify", action="store_true", help="Skip the verify-after-write check.")
        parser.add_argument("--block-size", type=int, default=None, help="Block size in bytes.")
        parser.add_argument("--kdf-time", type=int, default=None, help="Argon2 time cost.")
        parser.add_argument("--kdf-memory", type=int, default=None, help="Argon2 memory cost (KiB).")
        parser.add_argument("--once", action="store_true", help="Run a single cycle and exit.")

    def handle(self, *args, **options):
        passphrase = require_env_passphrase("dbs_schedule")
        if _follows_database(options):
            return self._run_database_schedule(options)
        plan = self._plan(options)
        interval = parse_interval(plan["interval"])
        if interval < MINIMUM_SENSIBLE_INTERVAL and not options["once"]:
            logger.warning("scheduling backups every %d seconds is very frequent", interval)

        os.makedirs(plan["output_dir"], exist_ok=True)
        stop = threading.Event()
        if not options["once"]:
            install_stop_handlers(stop)
            self.stdout.write(
                f"Backing up to {plan['output_dir']} every {plan['interval']}, "
                f"keeping {plan['keep']}."
            )

        failures = run_schedule(
            lambda: self._cycle(passphrase, plan),
            interval,
            once=options["once"],
            stop=stop,
        )
        if failures:
            raise CommandError(f"{failures} backup cycle(s) failed; see the dbs log.")
        if options["once"]:
            self.stdout.write(self.style.SUCCESS("Backup cycle complete."))

    def _plan(self, options) -> dict:
        output_dir = options["output_dir"] or setting("DBS_BACKUP_DIR", None)
        if not output_dir:
            raise CommandError(
                "Set --output-dir or the DBS_BACKUP_DIR setting so backups have a home."
            )
        keep = options["keep"] if options["keep"] is not None else setting("DBS_SCHEDULE_KEEP", 7)
        keep_remote = (
            options["keep_remote"]
            if options["keep_remote"] is not None
            else setting("DBS_SCHEDULE_KEEP_REMOTE", None)
        )
        kdf_params = None
        if options["kdf_time"] or options["kdf_memory"]:
            base = KDFParams()
            kdf_params = KDFParams(
                time_cost=options["kdf_time"] or base.time_cost,
                memory_cost=options["kdf_memory"] or base.memory_cost,
                parallelism=base.parallelism,
            )
        return {
            "interval": options["interval"] or setting("DBS_SCHEDULE_INTERVAL", "24h"),
            "output_dir": os.path.expanduser(str(output_dir)),
            "prefix": options["prefix"] or setting("DBS_BACKUP_PREFIX", DEFAULT_PREFIX),
            "keep": int(keep),
            "keep_remote": None if keep_remote is None else int(keep_remote),
            "push": _push_target(options["push"] or setting("DBS_SCHEDULE_PUSH_TARGET", None)),
            "database": options["database"],
            "compress": not options["no_compress"],
            "verify": not options["no_verify"],
            "block_size": options["block_size"],
            "kdf_params": kdf_params,
        }

    def _cycle(self, passphrase: str, plan: dict) -> None:
        try:
            schedule_runner.run_cycle(passphrase, plan)
        except DBSError as exc:
            raise CommandError(f"Backup failed: {exc}") from exc

    def _run_database_schedule(self, options) -> None:
        if options["once"]:
            try:
                schedule_runner.run_due(force=True)
            except DBSError as exc:
                raise CommandError(f"Backup failed: {exc}") from exc
            self.stdout.write(self.style.SUCCESS("Backup cycle complete."))
            return
        stop = threading.Event()
        install_stop_handlers(stop)
        self.stdout.write("Following the schedule set in the DBS panel.")
        while not stop.is_set():
            schedule_runner.tick()
            stop.wait(schedule_runner.TICK_SECONDS)


def _follows_database(options) -> bool:
    if any(options[name] is not None for name in PLAN_OPTIONS):
        return False
    schedule = schedule_runner.database_schedule()
    return schedule is not None and schedule.enabled
