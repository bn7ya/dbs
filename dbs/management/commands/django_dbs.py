from __future__ import annotations

from dbs.management.commands.dbs import ALIAS_TIP, Command as DbsCommand


class Command(DbsCommand):
    help = 'The DBS backup toolkit, under its old name. Prefer "manage.py dbs".'

    alias_tip = ALIAS_TIP
