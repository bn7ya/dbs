from __future__ import annotations

from django.core.management import load_command_class
from django.core.management.base import BaseCommand

SUBCOMMANDS = {
    "backup": ("dbs_backup", "Create a redundant, encrypted DBS backup file."),
    "restore": ("dbs_restore", "Restore a backup into the database and file storage."),
    "validate": ("dbs_validate", "Check a backup's structure, blocks and decryption."),
    "schedule": ("dbs_schedule", "Run backups on a repeating interval."),
    "connection": ("dbs_connection", "Show what a DBS manager needs to reach this project."),
    "health": ("dbs_health", "Report the health of this project's backups."),
    "audit": ("dbs_audit", "Verify that the audit trail was not changed."),
    "key": ("dbs_key", "Show the passphrase DBS derives from SECRET_KEY."),
    "security": ("dbs_security", "Inspect and unlock the admin session guard."),
    "ai": ("dbs_ai", "Install the DBS instructions for AI coding assistants."),
    "upgrade": ("dbs_upgrade", "Bring this project up to date with the installed DBS."),
}

UNCHECKED_SUBCOMMANDS = ("upgrade",)


class Command(BaseCommand):
    help = "The DBS backup toolkit. Run a subcommand, or nothing for an overview."

    def execute(self, *args, **options):
        if options.get("subcommand") in UNCHECKED_SUBCOMMANDS:
            options["skip_checks"] = True
        return super().execute(*args, **options)

    def add_arguments(self, parser):
        subparsers = parser.add_subparsers(dest="subcommand")
        for name, (module, description) in SUBCOMMANDS.items():
            child = subparsers.add_parser(name, help=description)
            load_command_class("dbs", module).add_arguments(child)

    def handle(self, *args, **options):
        name = options.get("subcommand")
        if not name:
            self.overview()
            return
        command = load_command_class("dbs", SUBCOMMANDS[name][0])
        command.stdout = self.stdout
        command.stderr = self.stderr
        command.style = self.style
        command.handle(*args, **options)

    def overview(self):
        self.stdout.write(self.style.MIGRATE_HEADING("DBS"))
        self.stdout.write(
            "Encrypted, redundant, self-healing backups for this Django project.\n"
        )
        for name, (_, description) in SUBCOMMANDS.items():
            self.stdout.write(f"  manage.py dbs {name:<9} {description}")
        self.stdout.write(
            "\nThe same commands answer to manage.py django_dbs and manage.py django-dbs."
        )
        self.stdout.write(
            "\nThe admin panel lives at /admin/dbs/ once you log in as a superuser."
        )
        self.stdout.write(
            "Run 'manage.py dbs ai' to install the DBS instructions for AI assistants."
        )
