from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from dbs import audit

ACTIONS = ("verify",)


class Command(BaseCommand):
    help = "Check that no audit row was changed or removed after it was written."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=ACTIONS, nargs="?", default="verify")

    def handle(self, *args, **options):
        check = audit.verify_chain()
        if not check.intact:
            raise CommandError(
                f"The audit trail is broken at link {check.broken_at}: {check.reason}."
            )
        self.stdout.write(
            self.style.SUCCESS(f"The audit trail is intact: {check.checked} rows checked.")
        )
        if check.checked:
            self.stdout.write(f"Head: link {check.checked}, {check.head}")
        if check.unsealed:
            self.stdout.write(
                self.style.WARNING(
                    f"{check.unsealed} finished rows are not sealed yet; they are sealed, "
                    "oldest first, as new audit rows are written."
                )
            )
        if check.unfinished:
            self.stdout.write(
                f"{check.unfinished} rows are still running and are sealed when they end."
            )
