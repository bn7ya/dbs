from __future__ import annotations

from dbs import checkpoints
from dbs.management.underlying import underlying_command


class Command(underlying_command("migrate")):
    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            "--no-checkpoint",
            action="store_true",
            help="Migrate without the backups DBS keeps before and after a migration.",
        )

    def handle(self, *args, **options):
        with checkpoints.session(skip=options.pop("no_checkpoint", False)) as session:
            try:
                return super().handle(*args, **options)
            except BaseException:
                for checkpoint in session.before.values():
                    self.stderr.write(checkpoints.restore_hint(checkpoint))
                raise
