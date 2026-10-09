from __future__ import annotations

from django.core.management import load_command_class
from django.core.management.base import BaseCommand, CommandError

SUBCOMMANDS = {
    "backup": ("dbs_backup", "Create a redundant, encrypted DBS backup file."),
    "restore": ("dbs_restore", "Restore a backup into the database and file storage."),
    "validate": ("dbs_validate", "Check a backup's structure, blocks and decryption."),
    "schedule": ("dbs_schedule", "Run backups on a repeating interval."),
    "health": ("dbs_health", "Report the health of this project's backups."),
    "key": ("dbs_key", "Show the passphrase DBS derives from SECRET_KEY."),
    "security": ("dbs_security", "Inspect and unlock the admin session guard."),
    "ai": ("dbs_ai", "Install the DBS instructions for AI coding assistants."),
    "upgrade": ("dbs_upgrade", "Bring this project up to date with the installed DBS."),
}

ALIAS_TIP = 'Tip: this command is also available as "manage.py dbs".'


class Command(BaseCommand):
    help = "The DBS backup toolkit. Run a subcommand, or nothing for an overview."

    alias_tip = ""

    def add_arguments(self, parser):
        subparsers = parser.add_subparsers(dest="subcommand")
        for name, (module, description) in SUBCOMMANDS.items():
            child = subparsers.add_parser(name, help=description)
            load_command_class("dbs", module).add_arguments(child)

    def handle(self, *args, **options):
        if self.alias_tip:
            self.stdout.write(self.style.WARNING(self.alias_tip))
        name = options.get("subcommand")
        if not name:
            self.overview()
            return
        command = load_command_class("dbs", SUBCOMMANDS[name][0])
        command.stdout = self.stdout
        command.stderr = self.stderr
        command.style = self.style
        try:
            command.handle(*args, **options)
        except CommandError:
            raise

    def overview(self):
        self.stdout.write(self.style.MIGRATE_HEADING("DBS"))
        self.stdout.write(
            "Encrypted, redundant, self-healing backups for this Django project.\n"
        )
        for name, (_, description) in SUBCOMMANDS.items():
            self.stdout.write(f"  manage.py dbs {name:<9} {description}")
        self.stdout.write(
            "\nThe admin panel lives at /admin/dbs/ once you log in as a superuser."
        )
        self.stdout.write(
            "Run 'manage.py dbs ai' to install the DBS instructions for AI assistants."
        )
