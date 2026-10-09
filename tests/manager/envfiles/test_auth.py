from __future__ import annotations

from uuid import uuid4

import pytest

from tests.manager.envfiles.conftest import LIST

VERSION = uuid4()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("get", LIST, {"server": str(uuid4())}),
        ("post", f"{LIST}pull/", {"server": str(uuid4())}),
        ("get", f"{LIST}{VERSION}/", None),
        ("get", f"{LIST}{VERSION}/compare/", {"to": str(uuid4())}),
        ("post", f"{LIST}{VERSION}/reveal/", {"password": "x"}),
        ("post", f"{LIST}{VERSION}/push/", {"password": "x"}),
    ],
)
def test_without_a_session_every_endpoint_is_refused(
    anonymous, network, method, path, body
):
    response = getattr(anonymous, method)(path, body)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "not_authenticated"
    assert network.opened == []
