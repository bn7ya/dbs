from __future__ import annotations

import os

from django.core.management.base import BaseCommand, CommandError

from dbs import audit
from dbs._cli import resolve_read_passphrase
from dbs.engine import validate_backup
from dbs.exceptions import DBSError, InvalidPassphrase
from dbs.io import file_digest
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
        parser.add_argument(
            "--passphrase-stdin",
            action="store_true",
            help="Read the passphrase from the first line of standard input and verify "
            "decryption end-to-end.",
        )

    def handle(self, *args, **options):
        name = os.path.basename(options["input"])
        with audit.track("backup.validate", target=name, data={"file": name}) as entry:
            data = options["input"]
            try:
                size, digest = file_digest(data)
            except OSError as exc:
                raise CommandError(f"Cannot read {data}: {exc}") from exc
            entry.data.update(size=size, sha256=digest)

            if options.get("passphrase") or options.get("passphrase_stdin"):
                given = options.get("passphrase")
                passphrase = resolve_read_passphrase(
                    None if given in (None, "__prompt__") else given,
                    from_stdin=options.get("passphrase_stdin", False),
                )
                try:
                    result = with_passphrase(
                        lambda secret: _decrypt_checked(data, secret), passphrase
                    )
                except DBSError as exc:
                    raise CommandError(f"Validation failed: {exc}") from exc
            else:
                result = validate_backup(data)
            entry.data.update(ok=bool(result.ok), decrypted=result.decrypted_ok)
            style = self.style.SUCCESS if result.ok else self.style.ERROR
            self.stdout.write(style(result.summary()))
            if not result.ok:
                raise CommandError("Validation failed.")


def _decrypt_checked(data, secret):
    result = validate_backup(data, secret)
    if result.decrypted_ok is False:
        raise InvalidPassphrase("The backup did not decrypt with this passphrase.")
    return result
