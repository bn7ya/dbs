from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from dbs._cli import resolve_passphrase
from dbs.engine import restore_backup
from dbs.exceptions import DBSError


class Command(BaseCommand):
    help = "Restore a DBS backup file into the database and file storage."

    def add_arguments(self, parser):
        parser.add_argument("input", help="Path to the .dbs backup file.")
        parser.add_argument("--passphrase", help="Encryption passphrase; visible to other local processes, prefer $DBS_PASSPHRASE or the interactive prompt.")
        parser.add_argument("--database", default="default", help="Database alias to restore into.")
        parser.add_argument("--no-data", action="store_true", help="Do not load database rows.")
        parser.add_argument("--no-files", action="store_true", help="Do not write files back.")

    def handle(self, *args, **options):
        passphrase = resolve_passphrase(options.get("passphrase"))
        try:
            with open(options["input"], "rb") as fh:
                data = fh.read()
        except OSError as exc:
            raise CommandError(f"Cannot read {options['input']}: {exc}") from exc

        try:
            result = restore_backup(
                data,
                passphrase,
                using=options["database"],
                load_data=not options["no_data"],
                write_files=not options["no_files"],
            )
        except DBSError as exc:
            raise CommandError(f"Restore failed: {exc}") from exc

        if result.healed:
            self.stdout.write(
                self.style.WARNING("Corruption detected and repaired: " + result.repair_report.summary())
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"Restored {result.records_loaded} records and {result.files_written} files."
            )
        )
