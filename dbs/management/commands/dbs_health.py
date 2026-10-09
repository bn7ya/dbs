from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from dbs.health import ERROR, WARN, report


class Command(BaseCommand):
    help = "Report the health of this project's backups."

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true", help="Print the report as JSON.")

    def handle(self, *args, **options):
        result = report()
        if options["json"]:
            self.stdout.write(json.dumps(result.as_dict()))
            return
        styles = {ERROR: self.style.ERROR, WARN: self.style.WARNING}
        for check in result.checks:
            style = styles.get(check.status, str)
            self.stdout.write(style(f"{check.status:<6} {check.name:<18} {check.message}"))
        self.stdout.write(f"overall {result.status}")
