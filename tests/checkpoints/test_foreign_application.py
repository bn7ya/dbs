"""Two projects that share a SECRET_KEY can decrypt each other's backups, and restore neither."""

from __future__ import annotations

import pytest

from tests.checkpoints.harness import Project


def backed_up(project, tmp_path, name):
    backup = tmp_path / name
    project.manage("dbs", "backup", str(backup))
    return backup


def test_both_projects_derive_the_same_passphrase(shop, depot):
    assert shop.manage("dbs", "key").out == depot.manage("dbs", "key").out


def test_a_backup_decrypts_in_the_other_project_and_names_its_application(shop, depot, tmp_path):
    backup = backed_up(shop, tmp_path, "shop.dbs")

    validated = depot.manage("dbs", "validate", str(backup), "--passphrase")

    assert "[VALID]" in validated.out
    assert "Application: shop" in validated.out


@pytest.mark.parametrize("options", [(), ("--flush",), ("--dry-run",)])
def test_the_shops_backup_is_refused_in_the_depot(shop, depot, tmp_path, options):
    backup = backed_up(shop, tmp_path, "shop.dbs")

    refused = depot.manage("dbs", "restore", str(backup), *options, check=False)

    assert refused.code != 0
    assert "belongs to the application 'shop', and this project is 'depot'" in refused.err
    assert depot.query("SELECT name, quantity FROM stock_item") == [["crate", 7]]
    assert depot.query("SELECT COUNT(*) FROM auth_user") == [[0]]
    assert depot.checkpoints() == []


def test_the_depots_backup_is_refused_in_the_shop(shop, depot, tmp_path):
    backup = backed_up(depot, tmp_path, "depot.dbs")

    refused = shop.manage("dbs", "restore", str(backup), "--flush", check=False)

    assert refused.code != 0
    assert "belongs to the application 'depot', and this project is 'shop'" in refused.err
    assert shop.query("SELECT username FROM auth_user") == [["ada"]]
    assert shop.query("SELECT COUNT(*) FROM ledger_entry") == [[2]]


def test_a_checkpoint_of_the_shop_is_refused_in_the_depot(shop, depot):
    shop.migrate_to("2")

    refused = depot.manage(
        "dbs", "restore", str(shop.checkpoint("before-migrate")), "--flush", check=False
    )

    assert refused.code != 0
    assert "belongs to the application 'shop'" in refused.err
    assert "stock_item" in depot.tables()


def test_the_refusal_is_in_the_audit_trail(shop, depot, tmp_path):
    backup = backed_up(shop, tmp_path, "shop.dbs")

    depot.manage("dbs", "restore", str(backup), check=False)

    assert depot.query(
        "SELECT status, error_code FROM dbs_auditevent WHERE action = 'backup.restore'"
    ) == [["failed", "ForeignBackup"]]


def test_the_same_project_in_another_folder_with_another_database_takes_the_backup(
    shop, make_project, tmp_path
):
    backup = backed_up(shop, tmp_path, "shop.dbs")
    copy = make_project(folder="shop-on-another-server")
    copy.at("1").manage("migrate", "--noinput")

    copy.manage("dbs", "restore", str(backup), "--flush")

    assert copy.query("SELECT username FROM auth_user") == [["ada"]]
    assert copy.query("SELECT COUNT(*) FROM ledger_entry") == [[2]]


def test_saying_it_is_another_applications_loads_what_this_project_has_models_for(
    shop, depot, tmp_path
):
    backup = backed_up(shop, tmp_path, "shop.dbs")

    depot.manage("dbs", "restore", str(backup), "--another-application")

    assert depot.query("SELECT username FROM auth_user") == [["ada"]]
    assert depot.query("SELECT name, quantity FROM stock_item") == [["crate", 7]]


def test_two_projects_with_one_package_name_are_told_apart_by_their_models(
    shop, make_project, tmp_path
):
    backup = backed_up(shop, tmp_path, "shop.dbs")
    namesake = make_project("other", "depot", folder="namesake")
    namesake.options["PROJECT_APPLICATION"] = "shop"
    namesake.manage("migrate", "--noinput")

    refused = namesake.manage("dbs", "restore", str(backup), check=False)

    assert refused.code != 0
    assert "named 'shop' like this project" in refused.err
    assert "none of the models it holds (ledger.account, ledger.tag, ledger.entry)" in refused.err


def test_a_name_of_its_own_tells_two_deployments_apart(shop, make_project, tmp_path):
    shop.options["PROJECT_APPLICATION"] = "shop-production"
    backup = backed_up(shop, tmp_path, "shop.dbs")
    staging = make_project(folder="staging")
    staging.options["PROJECT_APPLICATION"] = "shop-staging"
    staging.at("1").manage("migrate", "--noinput")

    refused = staging.manage("dbs", "restore", str(backup), check=False)
    staging.options["PROJECT_APPLICATION"] = "shop-production"
    taken = staging.manage("dbs", "restore", str(backup), "--flush")

    assert "belongs to the application 'shop-production'" in refused.err
    assert "Restored" in taken.out
    assert isinstance(staging, Project)
