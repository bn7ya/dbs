from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from dbs.connection import details


class Command(BaseCommand):
    help = "Show what a DBS manager needs to reach this project over SSH."

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true", help="Print the details as JSON.")

    def handle(self, *args, **options):
        info = details()
        if options["json"]:
            self.stdout.write(json.dumps(info))
            return
        for key, value in info.items():
            if key == "host_keys":
                for entry in value:
                    self.stdout.write(f"{'host key':<18} {entry['type']} {entry['fingerprint']}")
                continue
            if isinstance(value, list):
                value = ", ".join(value) or "-"
            self.stdout.write(f"{key.replace('_', ' '):<18} {value or '-'}")
