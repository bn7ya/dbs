from __future__ import annotations

import pytest

from tests.checkpoints.harness import Database, Project

SEED = """
from django.contrib.auth import get_user_model
from ledger.models import Account, Entry, Tag
get_user_model().objects.create_user("ada", password="correct-horse")
cash = Account.objects.create(name="Cash")
bank = Account.objects.create(name="Bank")
rent, food = Tag.objects.create(label="rent"), Tag.objects.create(label="food")
first = Entry.objects.create(account=cash, amount="12.50", note="first")
first.tags.add(rent, food)
Entry.objects.create(account=bank, amount="99.99", note="second")
"""


@pytest.fixture
def make_project(tmp_path, django_db_blocker):
    databases = []

    def make(source="project", package="shop", folder=None, backups=True, database=None):
        name = folder or package
        if database is None:
            with django_db_blocker.unblock():
                database = Database(tmp_path)
            databases.append(database)
        kept = (tmp_path / f"{name}-backups") if backups else None
        return Project(tmp_path / name, source, package, database, kept)

    yield make
    with django_db_blocker.unblock():
        for database in databases:
            database.drop()


@pytest.fixture
def shop(make_project):
    project = make_project()
    project.options["PROJECT_MAX_BACKUPS"] = 10
    project.at("1").manage("migrate", "--noinput")
    project.run(SEED)
    return project


@pytest.fixture
def depot(make_project):
    project = make_project("other", "depot")
    project.manage("migrate", "--noinput")
    project.run("from stock.models import Item\nItem.objects.create(name='crate', quantity=7)")
    return project
