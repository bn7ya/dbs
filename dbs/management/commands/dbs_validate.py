"""``manage.py dbs_validate`` -- check a backup's integrity without restoring."""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from dbs._cli import resolve_passphrase
from dbs.engine import validate_backup


class Command(BaseCommand):
    help = "Validate a DBS backup file (structure, block integrity, optional decrypt)."

    def add_arguments(self, parser):
        parser.add_argument("input", help="Path to the .dbs backup file.")
        parser.add_argument(
            "--passphrase",
            nargs="?",
            const="__prompt__",
            help="If given, also verify decryption end-to-end.",
        )

    def handle(self, *args, **options):
        try:
            with open(options["input"], "rb") as fh:
                data = fh.read()
        except OSError as exc:
            raise CommandError(f"Cannot read {options['input']}: {exc}") from exc

        passphrase = None
        if options.get("passphrase"):
            given = options["passphrase"]
            passphrase = resolve_passphrase(None if given == "__prompt__" else given)

        result = validate_backup(data, passphrase)
        style = self.style.SUCCESS if result.ok else self.style.ERROR
        self.stdout.write(style(result.summary()))
        if not result.ok:
            raise CommandError("Validation failed.")
