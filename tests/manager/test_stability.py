"""Every release from 0.8.0 on keeps the manager's terminal, API, MCP tools and the data it sealed."""

import io
from importlib import import_module
from types import SimpleNamespace

import pytest
from django.test.utils import override_settings

from dbs.manager import keystore, paths, vault
from dbs.manager.accounts.services.two_factor_service import (
    TwoFactorService,
    typed_recovery_code,
)
from dbs.manager.cli import build_parser
from dbs.manager.envfiles.services import vault_contexts as envfile_contexts
from dbs.manager.mcp import tools
from tests.stability import (
    destructive_migrations,
    parser_changes,
    parser_tree,
    recorded,
    released_migrations_missing,
    releases,
    route_changes,
    route_surface,
    schema_changes,
)

RECORDED = [release for release in releases() if recorded(release, "manager")]


@pytest.fixture(params=RECORDED, ids=lambda release: release.name)
def promised(request):
    return recorded(request.param, "manager")


@pytest.fixture
def sealing_key(promised):
    with override_settings(SECRET_KEY=promised["vectors"]["secret_key"], SECRET_KEY_FALLBACKS=[]):
        yield promised["vectors"]


def test_0_8_0_is_recorded():
    assert "0.8.0" in [release.name for release in RECORDED]


def test_every_terminal_command_keeps_its_options_and_arguments(promised):
    assert parser_changes("django_dbs", promised["terminal"], parser_tree(build_parser())) == []


def test_every_mcp_tool_stays_and_takes_what_it_took(promised):
    current = {tool.name: tool.input_schema for tool in tools.build(None)}

    problems = []
    for name, schema in promised["mcp"].items():
        problems += schema_changes(f"MCP tool {name}", schema, current.get(name))

    assert problems == []


def test_every_rest_route_and_method_stays(promised):
    assert route_changes(promised["routes"], route_surface("dbs.manager.urls")) == []


def test_released_migrations_stay_and_later_ones_drop_no_data(promised):
    for app_label, names in promised["migrations"].items():
        assert released_migrations_missing(app_label, names) == []
        assert destructive_migrations(app_label, names) == []


def test_a_data_folder_laid_out_as_recorded_still_opens(promised, tmp_path):
    layout = promised["data_folder"]
    key_file = tmp_path / layout["key_file"]
    key_file.parent.mkdir(mode=0o700)
    key_file.write_text("a-sealing-key-from-an-older-release\n", encoding="ascii")
    key_file.chmod(0o600)

    loaded = keystore.load(tmp_path, {keystore.STORE_ENV: keystore.FILE})

    assert loaded.value == "a-sealing-key-from-an-older-release"
    assert paths.DATABASE_FILE == layout["database_file"]
    assert paths.INSTANCE_FILE == layout["instance_file"]
    assert paths.BACKUPS_DIRECTORY == layout["backups_directory"]
    assert keystore.SERVICE == layout["keychain_service"]


def test_every_sealed_credential_still_opens(sealing_key):
    for source, sealed in sealing_key["sealed"].items():
        module, name = source.rsplit(".", 1)

        assert getattr(import_module(module), name) == sealed["context"], source
        assert (
            vault.unseal_text(bytes.fromhex(sealed["token"]), context=sealed["context"])
            == sealing_key["plaintext"]
        )


def test_a_sealed_backup_file_still_opens(sealing_key):
    sealed = sealing_key["sealed_file"]
    module, name = sealed["source"].rsplit(".", 1)

    opened = b"".join(
        vault.open_stream(io.BytesIO(bytes.fromhex(sealed["token"])), context=sealed["context"])
    )

    assert getattr(import_module(module), name) == sealed["context"]
    assert opened == sealed["content"].encode()


def test_two_factor_secrets_and_recovery_codes_still_match(sealing_key):
    recorded_two_factor = sealing_key["two_factor"]
    service = TwoFactorService(SimpleNamespace(pk=recorded_two_factor["account_id"]))
    typed = typed_recovery_code(recorded_two_factor["recovery_code"])

    assert service.opened(bytes.fromhex(recorded_two_factor["sealed_secret"])) == recorded_two_factor["secret"]
    assert service._digest(typed) == recorded_two_factor["recovery_digest"]


def test_an_env_version_keeps_its_fingerprint(sealing_key):
    env = sealing_key["env_fingerprint"]

    assert (
        vault.fingerprint(env["content"].encode(), context=envfile_contexts.CONTENT)
        == env["fingerprint"]
    )
