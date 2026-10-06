from io import StringIO

import pytest
from django.core.management import call_command


@pytest.mark.django_db
def test_every_model_change_ships_a_migration():
    out = StringIO()
    try:
        call_command("makemigrations", "dbs", check=True, dry_run=True, stdout=out)
    except SystemExit:
        pytest.fail("dbs models have changes with no migration:\n" + out.getvalue())
