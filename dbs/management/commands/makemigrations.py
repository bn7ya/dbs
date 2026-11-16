from __future__ import annotations

from dbs import checkpoints
from dbs.management.underlying import underlying_command


class Command(underlying_command("makemigrations")):
    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            "--no-checkpoint",
            action="store_true",
            help="Write the migration without checking that DBS can keep a checkpoint of it.",
        )

    def handle(self, *args, **options):
        skip = options.pop("no_checkpoint", False)
        if not (skip or options.get("check_changes") or options.get("dry_run")):
            checkpoints.require_ready(stdout=self.stdout)
        return super().handle(*args, **options)
