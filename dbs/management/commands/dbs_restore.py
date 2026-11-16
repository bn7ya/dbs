from __future__ import annotations

import os

from django.core.management.base import BaseCommand, CommandError

from dbs import audit, checkpoints
from dbs._cli import resolve_read_passphrase
from dbs.exceptions import DBSError
from dbs.io import file_digest
from dbs.keys import with_passphrase


class Command(BaseCommand):
    help = "Restore a DBS backup file into the database and file storage."

    def add_arguments(self, parser):
        parser.add_argument("input", help="Path to the .dbs backup file.")
        parser.add_argument("--passphrase", help="Encryption passphrase; visible to other local processes, prefer $DBS_PASSPHRASE or the interactive prompt.")
        parser.add_argument("--passphrase-stdin", action="store_true", help="Read the passphrase from the first line of standard input.")
        parser.add_argument("--database", default="default", help="Database alias to restore into.")
        parser.add_argument("--no-data", action="store_true", help="Do not load database rows.")
        parser.add_argument("--no-files", action="store_true", help="Do not write files back.")
        parser.add_argument("--dry-run", action="store_true", help="Read, decrypt and rehearse the restore in a rolled-back transaction, then change nothing.")
        parser.add_argument("--flush", action="store_true", help="Delete existing rows of the backed-up models before loading, so the restore replaces instead of merges.")
        parser.add_argument("--another-application", action="store_true", help="Load a backup that records another application than this project, which is refused otherwise.")
        parser.add_argument("--no-schema", action="store_true", help="Load a checkpoint's rows into the tables as they are, instead of rebuilding the tables it was taken from.")
        parser.add_argument("--no-checkpoint", action="store_true", help="Restore without the backups DBS keeps before and after a restore.")

    def handle(self, *args, **options):
        passphrase = resolve_read_passphrase(
            options.get("passphrase"), from_stdin=options["passphrase_stdin"]
        )
        name = os.path.basename(options["input"])
        with audit.track(
            "backup.restore",
            target=name,
            data={
                "file": name,
                "database": options["database"],
                "dry_run": options["dry_run"],
                "flushed": options["flush"],
            },
        ) as entry:
            try:
                size, digest = file_digest(options["input"])
            except OSError as exc:
                raise CommandError(f"Cannot read {options['input']}: {exc}") from exc
            entry.data.update(size=size, sha256=digest)
            try:
                result = with_passphrase(
                    lambda secret: checkpoints.restore(
                        options["input"],
                        secret,
                        using=options["database"],
                        checkpoint=not options.get("no_checkpoint", False),
                        stdout=self.stdout,
                        load_data=not options["no_data"],
                        write_files=not options["no_files"],
                        dry_run=options["dry_run"],
                        flush=options["flush"],
                        another_application=options.get("another_application", False),
                        schema=False if options.get("no_schema") else None,
                    ),
                    passphrase,
                )
            except DBSError as exc:
                raise CommandError(f"Restore failed: {exc}") from exc
            entry.data.update(restore_summary(result, options["dry_run"]))

        if result.healed:
            self.stdout.write(
                self.style.WARNING("Corruption detected and repaired: " + result.repair_report.summary())
            )
        if result.tables_rebuilt:
            self.describe_rebuild(result, options["dry_run"])
        if options["dry_run"]:
            if result.records_flushed:
                self.stdout.write(
                    f"Flush would first delete {result.records_flushed} existing rows."
                )
            self.stdout.write(
                self.style.SUCCESS(
                    f"Dry run: {result.records_would_load} records and "
                    f"{result.files_would_write} files would be restored; "
                    "nothing was written."
                )
            )
            if result.files_refused:
                for problem in result.files_refused:
                    self.stdout.write(self.style.ERROR(f"Would refuse {problem}"))
                raise CommandError(
                    f"Dry run: the restore would stop before loading any row, because "
                    f"{len(result.files_refused)} file(s) cannot be written. Allow their "
                    "directories in DBS_RESTORE_ROOTS, or map old roots with "
                    "DBS_RESTORE_PATH_MAP."
                )
            return
        if options["flush"] and not result.tables_rebuilt:
            self.stdout.write(
                f"Flushed {result.records_flushed} existing rows from the backed-up models before loading."
            )
        elif result.preexisting_models and not options["no_data"]:
            self.stdout.write(
                self.style.WARNING(
                    "Merged into existing rows for "
                    + ", ".join(result.preexisting_models)
                    + " (use --flush to replace instead)."
                )
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"Restored {result.records_loaded} records and {result.files_written} files."
            )
        )


    def describe_rebuild(self, result, dry_run):
        would = "would be" if dry_run else "were"
        self.stdout.write(
            f"{len(result.tables_rebuilt)} tables {would} rebuilt as the checkpoint's "
            "migrations describe them."
        )
        if result.migrations_unapplied:
            self.stdout.write(
                f"No longer applied ({len(result.migrations_unapplied)}): "
                + ", ".join(result.migrations_unapplied)
            )
        if result.migrations_recorded:
            self.stdout.write(
                f"Recorded as applied again ({len(result.migrations_recorded)}): "
                + ", ".join(result.migrations_recorded)
            )
        if result.raw_sql_migrations:
            self.stdout.write(
                self.style.WARNING(
                    "These migrations ran raw SQL, which rebuilding the tables does not "
                    "repeat: " + ", ".join(result.raw_sql_migrations)
                )
            )


def restore_summary(result, dry_run):
    rebuilt = (
        {"schema": True, "unapplied": list(result.migrations_unapplied)}
        if result.tables_rebuilt
        else {}
    )
    if dry_run:
        return {
            "records": result.records_would_load,
            "files": result.files_would_write,
            "files_refused": len(result.files_refused),
            "healed": bool(result.healed),
            **rebuilt,
        }
    return {
        "records": result.records_loaded,
        "files": result.files_written,
        "healed": bool(result.healed),
        **rebuilt,
    }
