from __future__ import annotations

import json

from dbs.manager.relocation.requirements import installed_versions, requirements_of

FROZEN = """Django==5.2
django-dbs @ file:///srv/wheelhouse/django_dbs-0.8.0-py3-none-any.whl#sha256=abc
shop-theme @ file:///home/deploy/wheels/shop_theme-1.2-py3-none-any.whl
vendored @ file:///tmp/vendored-1.0.tar.gz
-e git+https://example.com/shop.git@a1b2#egg=shop
requests @ git+https://example.com/requests.git@main
"""

LISTED = json.dumps(
    [
        {"name": "Django", "version": "5.2"},
        {"name": "django-dbs", "version": "0.8.0"},
        {"name": "Shop_Theme", "version": "1.2"},
    ]
)


def test_a_local_file_the_new_server_also_has_is_kept_and_others_are_asked_for_by_version():
    wanted, left_out = requirements_of(
        FROZEN,
        installed_versions(LISTED),
        lambda path: path == "/srv/wheelhouse/django_dbs-0.8.0-py3-none-any.whl",
    )

    assert wanted == [
        "Django==5.2",
        "django-dbs @ file:///srv/wheelhouse/django_dbs-0.8.0-py3-none-any.whl#sha256=abc",
        "shop-theme==1.2",
        "requests @ git+https://example.com/requests.git@main",
    ]
    assert left_out == ["vendored", "-e git+https://example.com/shop.git@a1b2#egg=shop"]


def test_an_unreadable_listing_pins_nothing():
    assert installed_versions("not json") == {}
    assert installed_versions('{"name": "x"}') == {}
    assert installed_versions('[{"name": "x"}, 3]') == {}
    assert requirements_of("thing @ file:///x.whl\n", {}, lambda path: False) == ([], ["thing"])
