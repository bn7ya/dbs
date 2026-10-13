from datetime import timedelta

import pytest
from django.utils import timezone

from dbs.manager.accounts.models import Account
from dbs.manager.accounts.repositories import UserRepository
from dbs.manager.mcp.server import build
from dbs.manager.permissions import Role
from tests.manager.servers.support import PASSWORD


def call(server, tool, **arguments):
    return server.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        }
    )["result"]


def instructions(server):
    return server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize"})["result"][
        "instructions"
    ]


@pytest.mark.django_db
def test_claude_can_never_do_more_than_the_account_it_acts_as(admin, make_server):
    make_server()
    viewer = UserRepository().create(
        username="vera", password=PASSWORD, role=Role.VIEWER
    )
    server = build(viewer)

    listed = call(server, "list_servers")
    taken = call(server, "take_backups", servers=["web-1"])
    checked = call(server, "check_servers", servers=["web-1"])

    assert not listed["isError"]
    assert taken["structuredContent"]["results"][0]["error"] == (
        "This needs the operator role or higher; your account is a viewer."
    )
    assert (
        "needs the operator role"
        in checked["structuredContent"]["results"][0]["problem"]
    )


@pytest.mark.django_db
def test_an_expired_password_is_named_in_the_instructions(admin):
    Account.objects.filter(user=admin).update(
        password_changed_at=timezone.now() - timedelta(days=40)
    )

    assert "the password of sara has expired" in instructions(build(admin))


@pytest.mark.django_db
def test_a_current_password_adds_nothing_to_the_instructions(admin):
    assert "expired" not in instructions(build(admin))
