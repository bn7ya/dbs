from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from dbs._cli import configured_passphrase
from dbs.exceptions import DBSError
from dbs.keys import candidate_passphrases, default_passphrase


class Command(BaseCommand):
    help = "Show the passphrase DBS derives from SECRET_KEY."

    def add_arguments(self, parser):
        parser.add_argument(
            "--show",
            action="store_true",
            help="Print the passphrase itself, not just where it comes from.",
        )

    def handle(self, *args, **options):
        configured = configured_passphrase()
        if configured:
            self.stdout.write(
                "DBS is using the configured DBS_PASSPHRASE, not SECRET_KEY."
            )
            if not options["show"]:
                return
        try:
            passphrase = configured or default_passphrase()
        except DBSError as exc:
            raise CommandError(str(exc)) from exc

        if not options["show"]:
            fallbacks = len(candidate_passphrases()) - 1
            self.stdout.write(
                "The backup passphrase is derived from SECRET_KEY. "
                f"{fallbacks} fallback key(s) will also be tried on restore."
            )
            self.stdout.write("Re-run with --show to print it.")
            return

        self.stdout.write(passphrase)
        self.stderr.write(
            self.style.WARNING(
                "Store this somewhere safe. A backup encrypted under a SECRET_KEY you "
                "lose, and did not keep in SECRET_KEY_FALLBACKS, cannot be opened."
            )
        )
