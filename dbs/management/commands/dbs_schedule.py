from __future__ import annotations

import logging
import os
import threading

from django.core.management.base import BaseCommand, CommandError

from dbs._cli import require_env_passphrase
from dbs.conf import setting
from dbs.crypto.kdf import KDFParams
from dbs.engine import create_backup
from dbs.exceptions import DBSError
from dbs.naming import DEFAULT_PREFIX, backup_filename
from dbs.retention import prune_directory, prune_remote
from dbs.scheduling import install_stop_handlers, parse_interval, run_schedule
from dbs.transports.ssh import SSHTarget, open_session

logger = logging.getLogger("dbs")

MINIMUM_SENSIBLE_INTERVAL = 60


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
            "push": options["push"] or setting("DBS_SCHEDULE_PUSH_TARGET", None),
            "database": options["database"],
            "compress": not options["no_compress"],
            "verify": not options["no_verify"],
            "block_size": options["block_size"],
            "kdf_params": kdf_params,
        }

    def _cycle(self, passphrase: str, plan: dict) -> None:
        name = _available_name(plan["output_dir"], plan["prefix"])
        output = os.path.join(plan["output_dir"], name)
        extra = {"block_size": plan["block_size"]} if plan["block_size"] else {}

        try:
            container = create_backup(
                passphrase,
                using=plan["database"],
                compress=plan["compress"],
                verify=plan["verify"],
                kdf_params=plan["kdf_params"],
                output=output,
                **extra,
            )
        except DBSError as exc:
            raise CommandError(f"Backup failed: {exc}") from exc

        logger.info("scheduled backup wrote %s (%d bytes)", output, len(container))
        prune_directory(plan["output_dir"], plan["keep"], plan["prefix"])

        if plan["push"]:
            self._push(name, output, plan)

    def _push(self, name: str, output: str, plan: dict) -> None:
        target = SSHTarget.from_settings(plan["push"])
        with open_session(target) as session:
            session.push(output, name)
            if plan["keep_remote"] is not None:
                prune_remote(session, plan["keep_remote"], plan["prefix"])


def _available_name(directory: str, prefix: str) -> str:
    for ordinal in range(1, 1000):
        name = backup_filename(prefix, ordinal=ordinal)
        if not os.path.exists(os.path.join(directory, name)):
            return name
    raise CommandError("Cannot find an unused backup filename for this second.")
