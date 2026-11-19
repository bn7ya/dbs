import os

import pytest
from django.db import transaction

from dbs import transactions as units
from dbs.transports import SSHTarget, open_session
from tests import transactions
from tests.testapp.models import Author

COUNTS = "def run(model):\n    return model.objects.count()\n"
CALLS = "def run(call):\n    return call()\n"


def as_dbs(source):
    namespace = {}
    exec(compile(source, os.path.join(transactions.PACKAGE, "probe.py"), "exec"), namespace)
    return namespace["run"]


@pytest.mark.django_db
def test_a_statement_dbs_sends_outside_a_transaction_is_caught():
    as_dbs(COUNTS)(Author)

    caught = transactions.watch.taken()

    assert [(entry.verb, entry.alias) for entry in caught] == [("SELECT", "default")]
    assert caught[0].site.endswith("probe.py:2 in run")
    assert "probe.py:2 in run" in str(transactions.TransactionRuleBroken(caught))


@pytest.mark.django_db
@pytest.mark.parametrize("unit", [units.reading, units.atomic, transaction.atomic])
def test_a_statement_inside_a_transaction_passes(unit):
    with unit():
        as_dbs(COUNTS)(Author)

    assert transactions.watch.taken() == []


@pytest.mark.django_db(databases=["default", "secondary"])
def test_a_transaction_on_another_database_does_not_cover_the_statement():
    with units.reading_on("secondary"):
        as_dbs(COUNTS)(Author)

    assert [entry.alias for entry in transactions.watch.taken()] == ["default"]


@pytest.mark.django_db
def test_a_statement_of_the_project_is_not_held_to_the_rule():
    Author.objects.count()
    as_dbs(CALLS)(lambda: Author.objects.count())

    assert transactions.watch.taken() == []


@pytest.mark.django_db
def test_reaching_a_server_inside_a_transaction_is_caught(fake_ssh):
    fake_ssh.make_remote_dir("/var/backups")
    target = SSHTarget(host="h.example.com", username="deploy", remote_dir="/var/backups")
    with open_session(target) as session:
        session.names()
        assert transactions.watch.taken() == []
        with units.atomic():
            session.names()

    caught = transactions.watch.taken()

    assert [(entry.call, entry.alias) for entry in caught] == [("SSHSession.names", "default")]
    assert "SSHSession.names" in str(transactions.TransactionRuleBroken(caught))


def test_a_broken_rule_fails_the_test_that_broke_it():
    class Outcome:
        error = None

        def force_exception(self, error):
            self.error = error

    found = [transactions.Outside("dbs/probe.py:2 in run", "SELECT", "default", "MainThread")]
    outcome = Outcome()

    transactions.fail(outcome, found)

    assert isinstance(outcome.error, transactions.TransactionRuleBroken)
    with pytest.raises(transactions.TransactionRuleBroken, match="probe.py:2 in run"):
        transactions.fail(object(), found)
