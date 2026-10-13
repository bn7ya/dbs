from __future__ import annotations

import os

from django.core.management.base import BaseCommand, CommandError

from dbs import audit
from dbs._cli import passphrase_source, resolve_passphrase
from dbs.crypto.kdf import KDFParams
from dbs.engine import write_backup
from dbs.exceptions import DBSError


class Command(BaseCommand):
    help = "Create a redundant, encrypted DBS backup file."

    def add_arguments(self, parser):
        parser.add_argument("output", help="Path to write the .dbs backup file to.")
        parser.add_argument("--passphrase", help="Encryption passphrase; visible to other local processes, prefer $DBS_PASSPHRASE or the interactive prompt.")
        parser.add_argument("--passphrase-stdin", action="store_true", help="Read the passphrase from the first line of standard input.")
        parser.add_argument("--database", default="default", help="Database alias to back up.")
        parser.add_argument("--no-compress", action="store_true", help="Disable zlib compression.")
        parser.add_argument("--no-verify", action="store_true", help="Skip the verify-after-write check.")
        parser.add_argument("--block-size", type=int, default=None, help="Block size in bytes.")
        parser.add_argument("--kdf-time", type=int, default=None, help="Argon2 time cost.")
        parser.add_argument("--kdf-memory", type=int, default=None, help="Argon2 memory cost (KiB).")
        parser.add_argument("--allow-missing-files", action="store_true", help="Back up even when a source file is missing or unreadable, listing what was left out.")

    def handle(self, *args, **options):
        passphrase = resolve_passphrase(
            options.get("passphrase"),
            confirm=True,
            from_stdin=options["passphrase_stdin"],
        )

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

        output = options["output"]
        skipped_files: list = []
        with audit.track(
            "backup.create",
            target=os.path.basename(output),
            data={"file": os.path.basename(output), "database": options["database"]},
        ) as entry:
            try:
                summary = write_backup(
                    output,
                    passphrase,
                    using=options["database"],
                    compress=not options["no_compress"],
                    verify=not options["no_verify"],
                    kdf_params=kdf_params,
                    allow_missing_files=options.get("allow_missing_files", False),
                    skipped_files=skipped_files,
                    **extra,
                )
            except DBSError as exc:
                raise CommandError(f"Backup failed: {exc}") from exc
            except OSError as exc:
                raise CommandError(f"Cannot write {output}: {exc.strerror or exc}.") from exc
            entry.data.update(
                size=summary.bytes_written,
                sha256=summary.sha256,
                verified=not options["no_verify"],
                compressed=not options["no_compress"],
            )
            audit.record_backup(output, summary.bytes_written, summary.sha256, options["database"])

        source = passphrase_source(
            options.get("passphrase"), from_stdin=options["passphrase_stdin"]
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Wrote {options['output']} ({summary.bytes_written:,} bytes), "
                "verified, two redundant copies + Reed-Solomon parity."
            )
        )
        if skipped_files:
            self.stdout.write(
                self.style.WARNING(
                    f"Left out {len(skipped_files)} source file(s) that could not be read: "
                    + "; ".join(skipped_files)
                )
            )
        self.stdout.write(f"Passphrase came from {source}.")

