from __future__ import annotations

from uuid import uuid4

import pytest

from tests.manager.envfiles.conftest import LIST

CHANGED = (
    b'SECRET_KEY=another\nexport DATABASE_URL="postgres://app:x@db/app"\nNEW_KEY=1\n'
)


def compare(api, version_id, to):
    return api.get(f"{LIST}{version_id}/compare/", {"to": to})


@pytest.mark.django_db
def test_two_versions_compare_by_name(api, server, env_file, pull, logged):
    old = pull(server)["version"]["id"]
    env_file.write_bytes(CHANGED)
    new = pull(server)["version"]["id"]

    response = compare(api, old, new)

    assert response.status_code == 200
    assert response.json() == {
        "from": old,
        "to": new,
        "added": ["NEW_KEY"],
        "removed": ["DEBUG"],
        "changed": ["SECRET_KEY", "DATABASE_URL"],
    }
    assert compare(api, new, old).json() == {
        "from": new,
        "to": old,
        "added": ["DEBUG"],
        "removed": ["NEW_KEY"],
        "changed": ["SECRET_KEY", "DATABASE_URL"],
    }
    assert logged("env.reveal") == []


@pytest.mark.django_db
def test_a_version_compared_with_itself_has_no_differences(api, server, pull):
    version = pull(server)["version"]["id"]

    assert compare(api, version, version).json() == {
        "from": version,
        "to": version,
        "added": [],
        "removed": [],
        "changed": [],
    }


@pytest.mark.django_db
def test_versions_of_two_servers_are_not_compared(
    api, make_server, server, env_file, pull
):
    other = make_server(name="web-2", host="10.0.0.6", env_path=str(env_file))
    mine, theirs = pull(server)["version"]["id"], pull(other)["version"]["id"]

    response = compare(api, mine, theirs)

    assert (response.status_code, response.json()["error"]["code"]) == (
        400,
        "different_servers",
    )


@pytest.mark.django_db
def test_an_unknown_version_on_either_side_is_not_found(api, server, pull):
    version = pull(server)["version"]["id"]

    for pair in ((uuid4(), version), (version, uuid4())):
        response = compare(api, *pair)
        assert (response.status_code, response.json()["error"]["code"]) == (
            404,
            "not_found",
        )


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("query", "code"), [({}, "required"), ({"to": "previous"}, "invalid")]
)
def test_a_comparison_needs_the_other_versions_id(api, server, pull, query, code):
    version = pull(server)["version"]["id"]

    response = api.get(f"{LIST}{version}/compare/", query)

    assert response.status_code == 400
    assert response.json()["error"]["fields"] == {"to": [code]}
