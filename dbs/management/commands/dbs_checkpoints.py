from __future__ import annotations

import json

from django.core.management.base import BaseCommand
from django.db import connections

from dbs import checkpoints


class Command(BaseCommand):
    help = "List the checkpoints DBS keeps around migrations and restores."

    def add_arguments(self, parser):
        parser.add_argument("--database", default=None, help="Only this database alias.")
        parser.add_argument("--json", action="store_true", help="Print the list as JSON.")

    def handle(self, *args, **options):
        databases = [options["database"]] if options.get("database") else list(connections)
        found = checkpoints.listing(databases)
        if options.get("json"):
            self.stdout.write(json.dumps(found))
            return
        if not checkpoints.directory():
            self.stdout.write("DBS_BACKUP_DIR is not set, so DBS keeps no checkpoints.")
            return
        if not found:
            self.stdout.write(f"No checkpoints in {checkpoints.directory()} yet.")
            return
        for entry in found:
            what = entry["role"].replace("-", " a ", 1)
            steps = entry["migrations"]
            detail = "" if not steps else ": " + ", ".join(steps)
            self.stdout.write(
                f"{entry['taken_at']}  {what}{detail}\n"
                f"    {entry['path']} ({entry['size']:,} bytes)"
            )
        self.stdout.write(
            "\nPut one back, schema and rows, with: manage.py dbs restore PATH --flush"
        )
