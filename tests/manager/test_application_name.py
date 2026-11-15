from __future__ import annotations

from dbs import identity


def test_the_managers_exports_belong_to_the_manager_not_to_a_package_named_dbs():
    assert identity.application_name() == "dbs-manager"
    assert identity.is_named_by_setting()
