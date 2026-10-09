from __future__ import annotations

import pytest
from rest_framework.exceptions import ValidationError

from dbs.manager.files.exceptions import NoAllowedFolders, PathOutsideRoots
from dbs.manager.files.paths import (
    Located,
    allowed_roots,
    entry_name,
    locate,
    resolved,
    within,
)

ROOTS = ["/srv/app/media", "/var/backups/e2e"]


@pytest.mark.parametrize(
    ("path", "root"),
    [
        ("/srv/app", "/srv/app"),
        ("/srv/app/media", "/srv/app"),
        ("/srv/app/media/deep/er", "/srv/app"),
        ("/srv/app/..data", "/srv/app"),
        ("/", "/"),
        ("/etc/passwd", "/"),
    ],
)
def test_a_path_is_within_a_root_it_equals_or_sits_below(path, root):
    assert within(path, root)


@pytest.mark.parametrize(
    ("path", "root"),
    [
        ("/srv/app2", "/srv/app"),
        ("/srv/application/x", "/srv/app"),
        ("/srv/ap", "/srv/app"),
        ("/srv", "/srv/app"),
        ("/", "/srv/app"),
        ("/etc", "/srv/app"),
    ],
    ids=["prefix", "longer-name", "shorter-name", "parent", "slash", "elsewhere"],
)
def test_a_path_that_only_starts_like_a_root_is_not_within_it(path, root):
    assert not within(path, root)


def test_roots_are_normalised_once_each_and_a_bad_one_is_left_out():
    roots = [
        "/srv/app/media/",
        "//srv//app/media",
        "relative",
        "/srv/../etc",
        "/a\x00b",
        "/",
        "/",
    ]

    assert allowed_roots(roots) == ["/srv/app/media", "/"]


@pytest.mark.parametrize(
    ("typed", "located"),
    [
        ("/srv/app/media", Located("/srv/app/media", "/srv/app/media")),
        ("/srv/app/media/", Located("/srv/app/media", "/srv/app/media")),
        (
            "//srv//app/./media/logo.png",
            Located("/srv/app/media/logo.png", "/srv/app/media"),
        ),
        (
            "/var/backups/e2e/db.sql.gz",
            Located("/var/backups/e2e/db.sql.gz", "/var/backups/e2e"),
        ),
        (
            "/srv/app/media/my folder/ x ",
            Located("/srv/app/media/my folder/ x ", "/srv/app/media"),
        ),
        (
            "/srv/app/media/..hidden",
            Located("/srv/app/media/..hidden", "/srv/app/media"),
        ),
    ],
)
def test_a_path_in_a_root_is_located_normalised(typed, located):
    assert locate(typed, ROOTS) == located


@pytest.mark.parametrize(
    "typed",
    [
        "",
        "srv/app/media",
        "./srv/app/media",
        "~/media",
        "/srv/app/media/..",
        "/srv/app/media/../../../etc/passwd",
        "/srv/app/media/sub/../logo.png",
        "/srv/app/media/a\x00b",
    ],
    ids=["empty", "relative", "dot", "home", "up", "climb", "up-and-back", "nul"],
)
def test_a_path_that_is_not_absolute_climbs_or_holds_a_nul_is_refused(typed):
    with pytest.raises(ValidationError) as refused:
        locate(typed, ROOTS)

    assert refused.value.get_codes() == {"path": ["absolute_path_required"]}


@pytest.mark.parametrize(
    "typed",
    [
        "/",
        "/etc/passwd",
        "/srv/app",
        "/srv/app/media2",
        "/srv/app/media2/x",
        "/var/backups/e2e-old",
    ],
    ids=["slash", "elsewhere", "parent", "prefix", "prefix-below", "prefix-other-root"],
)
def test_a_path_in_no_root_is_outside(typed):
    with pytest.raises(PathOutsideRoots) as refused:
        locate(typed, ROOTS)

    assert (refused.value.status_code, refused.value.default_code) == (
        403,
        "path_outside_roots",
    )


def test_a_server_with_no_roots_has_nothing_to_locate():
    with pytest.raises(NoAllowedFolders) as refused:
        locate("/srv/app/media", [])

    assert (refused.value.status_code, refused.value.default_code) == (
        400,
        "no_allowed_folders",
    )


def test_the_root_slash_holds_every_absolute_path():
    assert locate("/etc/passwd", ["/"]) == Located("/etc/passwd", "/")
    assert locate("/", ["/"]).parent is None


def test_nested_roots_locate_a_path_in_the_innermost():
    roots = ["/srv", "/srv/app/media"]

    assert locate("/srv/app/media/x", roots).root == "/srv/app/media"
    assert locate("/srv/app/x", roots).root == "/srv"
    assert locate("/srv/app/media", roots).parent is None


@pytest.mark.parametrize(
    ("typed", "parent", "name"),
    [
        ("/srv/app/media", None, "media"),
        ("/srv/app/media/logo.png", "/srv/app/media", "logo.png"),
        ("/srv/app/media/Docs/report.pdf", "/srv/app/media/Docs", "report.pdf"),
    ],
)
def test_the_way_up_stops_at_a_root(typed, parent, name):
    located = locate(typed, ROOTS)

    assert (located.parent, located.name) == (parent, name)


@pytest.mark.parametrize(
    ("answer", "real_roots", "path"),
    [
        ("/data/media", ["/data/media"], "/data/media"),
        ("/data/media/x", ["/data/media"], "/data/media/x"),
        ("/data/media/x/", ["/data/media"], "/data/media/x"),
        ("/etc/passwd", ["/data/media", "/"], "/etc/passwd"),
    ],
)
def test_an_answer_in_a_real_root_is_the_path_acted_on(answer, real_roots, path):
    assert resolved(answer, real_roots) == path


@pytest.mark.parametrize(
    ("answer", "real_roots"),
    [
        ("/etc/passwd", ["/data/media"]),
        ("/data/media2", ["/data/media"]),
        ("/data", ["/data/media"]),
        ("data/media/x", ["/data/media"]),
        ("/data/media/../../etc", ["/data/media"]),
        ("", ["/data/media"]),
        ("/data/media/x", []),
    ],
    ids=[
        "escape",
        "prefix",
        "parent",
        "relative",
        "climb",
        "empty",
        "no-root-resolved",
    ],
)
def test_an_answer_in_no_real_root_is_outside(answer, real_roots):
    with pytest.raises(PathOutsideRoots):
        resolved(answer, real_roots)


@pytest.mark.parametrize(
    "typed",
    [
        "photos",
        "my photos",
        ".hidden",
        "...",
        "نسخة الليل",
        "a.b.c",
        "-rf",
        "ن" * 127 + "x",
    ],
)
def test_a_name_that_can_be_one_is_kept_as_typed(typed):
    assert entry_name(typed) == typed


@pytest.mark.parametrize(
    "typed",
    [
        "",
        ".",
        "..",
        "a/b",
        "/a",
        "a\\b",
        "a\x00b",
        "a\nb",
        "\x1b[31m",
        "‮gpj.exe",
        "a b",
        "ن" * 128,
        "x" * 256,
    ],
    ids=[
        "empty",
        "dot",
        "dot-dot",
        "slash",
        "leading-slash",
        "backslash",
        "nul",
        "newline",
        "escape",
        "rtl-override",
        "no-break-space",
        "256-bytes-arabic",
        "256-bytes-latin",
    ],
)
def test_a_name_that_cannot_be_one_is_refused(typed):
    assert entry_name(typed) is None
