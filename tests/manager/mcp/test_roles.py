from datetime import timedelta

import pytest
from django.utils import timezone

from dbs.manager.accounts.models import Account
from dbs.manager.accounts.repositories import UserRepository
from dbs.manager.mcp.server import build
from dbs.manager.permissions import Role
from tests.manager.servers.support import PASSWORD


def call(toolbox, tool, **arguments):
    return toolbox.handle(
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
def test_claude_can_never_do_more_than_the_account_it_acts_as(admin, make_application):
    make_application()
    viewer = UserRepository().create(
        username="vera", password=PASSWORD, role=Role.VIEWER
    )
    toolbox = build(viewer)

    listed = call(toolbox, "list_servers")
    applications = call(toolbox, "list_applications")
    taken = call(toolbox, "take_backups", applications=["web-1"])
    checked = call(toolbox, "check_servers", servers=["web-1"])
    checked_applications = call(toolbox, "check_applications", applications=["web-1"])
    found = call(toolbox, "discover_applications", server="web-1", folder="/srv/app")
    added = call(
        toolbox, "add_application", server="web-1", folder="/srv/app", name="shop"
    )

    assert not listed["isError"] and not applications["isError"]
    assert taken["structuredContent"]["results"][0]["error"] == (
        "This needs the operator role or higher; your account is a viewer."
    )
    assert (
        "needs the operator role"
        in checked["structuredContent"]["results"][0]["problem"]
    )
    assert (
        "needs the operator role"
        in checked_applications["structuredContent"]["results"][0]["problem"]
    )
    for refused in (found, added):
        assert refused["isError"]
        assert refused["content"][0]["text"] == (
            "This needs the admin role or higher; your account is a viewer."
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
