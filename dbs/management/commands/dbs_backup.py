from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from dbs._cli import resolve_passphrase
from dbs.crypto.kdf import KDFParams
from dbs.engine import create_backup
from dbs.exceptions import DBSError


class Command(BaseCommand):
    help = "Create a redundant, encrypted DBS backup file."

    def add_arguments(self, parser):
        parser.add_argument("output", help="Path to write the .dbs backup file to.")
        parser.add_argument("--passphrase", help="Encryption passphrase; visible to other local processes, prefer $DBS_PASSPHRASE or the interactive prompt.")
        parser.add_argument("--database", default="default", help="Database alias to back up.")
        parser.add_argument("--no-compress", action="store_true", help="Disable zlib compression.")
        parser.add_argument("--no-verify", action="store_true", help="Skip the verify-after-write check.")
        parser.add_argument("--block-size", type=int, default=None, help="Block size in bytes.")
        parser.add_argument("--kdf-time", type=int, default=None, help="Argon2 time cost.")
        parser.add_argument("--kdf-memory", type=int, default=None, help="Argon2 memory cost (KiB).")

    def handle(self, *args, **options):
        passphrase = resolve_passphrase(options.get("passphrase"), confirm=True)

        kdf_params = None
        if options["kdf_time"] or options["kdf_memory"]:
            base = KDFParams()
            kdf_params = KDFParams(
                time_cost=options["kdf_time"] or base.time_cost,
                memory_cost=options["kdf_memory"] or base.memory_cost,
                parallelism=base.parallelism,
            )

        extra = {}
        if options["block_size"]:
            extra["block_size"] = options["block_size"]

        try:
            container = create_backup(
                passphrase,
                using=options["database"],
                compress=not options["no_compress"],
                verify=not options["no_verify"],
                kdf_params=kdf_params,
                output=options["output"],
                **extra,
            )
        except DBSError as exc:
            raise CommandError(f"Backup failed: {exc}") from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"Wrote {options['output']} ({len(container):,} bytes), "
                "verified, two redundant copies + Reed-Solomon parity."
            )
        )
