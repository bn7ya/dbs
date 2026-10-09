from __future__ import annotations

import pytest

from dbs.manager.common.paths import absolute_path


@pytest.mark.parametrize(
    ("typed", "normalised"),
    [
        ("/srv/app", "/srv/app"),
        ("/srv/app/", "/srv/app"),
        ("//srv//app/./media/", "/srv/app/media"),
        ("/", "/"),
        ("/srv/my folder", "/srv/my folder"),
        ("/srv/..data", "/srv/..data"),
    ],
)
def test_an_absolute_path_is_normalised(typed, normalised):
    assert absolute_path(typed) == normalised


@pytest.mark.parametrize(
    "typed",
    ["", "srv/app", "./srv", "~/app", "/srv/../etc", "/srv/..", "/srv/a\x00b"],
)
def test_a_path_that_is_not_absolute_or_climbs_is_refused(typed):
    assert absolute_path(typed) is None
