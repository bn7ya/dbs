from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from dbs._cli import resolve_read_passphrase
from dbs.engine import validate_backup
from dbs.keys import with_passphrase


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

        if options.get("passphrase"):
            given = options["passphrase"]
            passphrase = resolve_read_passphrase(None if given == "__prompt__" else given)
            result = with_passphrase(
                lambda secret: validate_backup(data, secret), passphrase
            )
        else:
            result = validate_backup(data)
        style = self.style.SUCCESS if result.ok else self.style.ERROR
        self.stdout.write(style(result.summary()))
        if not result.ok:
            raise CommandError("Validation failed.")
