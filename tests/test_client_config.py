"""Client config: discovery, merging, validation and secret hygiene."""

import os

import pytest

from dbs.client.config import (
    load_client_config,
    resolve_client_passphrase,
)
from dbs.exceptions import ConfigurationError

MINIMAL = """
[servers.prod]
host = "app.example.com"
username = "deploy"
"""

TWO_SERVERS = """
[defaults]
dest = "~/backups"
keep = 14

[servers.prod]
host = "app.example.com"
username = "deploy"
keep = 30

[servers.staging]
host = "staging.example.com"
username = "ubuntu"
"""


def write_config(tmp_path, text, name="dbs-client.toml", mode=0o600):
    path = tmp_path / name
    path.write_text(text)
    os.chmod(path, mode)
    return str(path)


def test_loads_a_single_server(tmp_path):
    config = load_client_config(write_config(tmp_path, MINIMAL))
    profile = config.server()
    assert profile.name == "prod"
    assert profile.host == "app.example.com"
    assert profile.port == 22


def test_defaults_are_inherited_and_overridden(tmp_path):
    config = load_client_config(write_config(tmp_path, TWO_SERVERS))
    assert config.servers["prod"].keep == 30
    assert config.servers["staging"].keep == 14
    assert config.servers["staging"].dest == "~/backups"


def test_ambiguous_server_selection_is_refused(tmp_path):
    config = load_client_config(write_config(tmp_path, TWO_SERVERS))
    with pytest.raises(ConfigurationError) as excinfo:
        config.server()
    assert "--server" in str(excinfo.value)
    assert config.server("staging").host == "staging.example.com"


def test_default_server_resolves_the_ambiguity(tmp_path):
    text = TWO_SERVERS.replace("[defaults]", '[defaults]\nserver = "staging"')
    config = load_client_config(write_config(tmp_path, text))
    assert config.server().name == "staging"


def test_an_unknown_server_name_lists_what_exists(tmp_path):
    config = load_client_config(write_config(tmp_path, TWO_SERVERS))
    with pytest.raises(ConfigurationError) as excinfo:
        config.server("production")
    assert "prod" in str(excinfo.value)


def test_a_typo_in_a_key_is_not_ignored(tmp_path):
    text = MINIMAL + 'known_host = "/tmp/known_hosts"\n'
    with pytest.raises(ConfigurationError) as excinfo:
        load_client_config(write_config(tmp_path, text))
    assert "known_host" in str(excinfo.value)


def test_a_missing_host_is_reported_with_the_profile_name(tmp_path):
    with pytest.raises(ConfigurationError) as excinfo:
        load_client_config(write_config(tmp_path, '[servers.prod]\nusername = "deploy"\n'))
    assert "prod" in str(excinfo.value)


def test_a_world_readable_file_with_a_literal_secret_is_refused(tmp_path):
    text = MINIMAL + 'passphrase = "hunter2"\n'
    with pytest.raises(ConfigurationError) as excinfo:
        load_client_config(write_config(tmp_path, text, mode=0o644))
    assert "chmod 600" in str(excinfo.value)


def test_the_same_file_is_accepted_at_mode_600(tmp_path):
    text = MINIMAL + 'passphrase = "hunter2"\n'
    config = load_client_config(write_config(tmp_path, text, mode=0o600))
    assert config.server().passphrase == "hunter2"


def test_environment_indirection_needs_no_tight_permissions(tmp_path):
    text = MINIMAL + 'passphrase_env = "DBS_PASSPHRASE"\n'
    config = load_client_config(write_config(tmp_path, text, mode=0o644))
    assert config.server().passphrase_env == "DBS_PASSPHRASE"


def test_a_writable_config_is_refused_even_without_secrets(tmp_path):
    with pytest.raises(ConfigurationError) as excinfo:
        load_client_config(write_config(tmp_path, MINIMAL, mode=0o666))
    assert "writable" in str(excinfo.value)


def test_the_config_path_comes_from_the_environment(tmp_path, monkeypatch):
    path = write_config(tmp_path, MINIMAL, name="elsewhere.toml")
    monkeypatch.setenv("DBS_CLIENT_CONFIG", path)
    assert load_client_config().server().host == "app.example.com"


def test_the_working_directory_is_searched(tmp_path, monkeypatch):
    write_config(tmp_path, MINIMAL)
    monkeypatch.delenv("DBS_CLIENT_CONFIG", raising=False)
    monkeypatch.chdir(tmp_path)
    assert load_client_config().server().name == "prod"


def test_a_missing_config_points_at_init(tmp_path, monkeypatch):
    monkeypatch.delenv("DBS_CLIENT_CONFIG", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("dbs.client.config.SEARCH_PATHS", ())
    with pytest.raises(ConfigurationError) as excinfo:
        load_client_config()
    assert "dbs-client init" in str(excinfo.value)


def test_home_relative_key_paths_reach_the_ssh_target(tmp_path):
    text = MINIMAL + 'key_filename = "~/keys/prod.pem"\n'
    profile = load_client_config(write_config(tmp_path, text)).server()
    assert profile.ssh_target().key_filename == os.path.expanduser("~/keys/prod.pem")


def test_password_authentication_reaches_the_ssh_target(tmp_path, monkeypatch):
    monkeypatch.setenv("DBS_TEST_PASSWORD", "s3cret")
    text = MINIMAL + 'password_env = "DBS_TEST_PASSWORD"\n'
    profile = load_client_config(write_config(tmp_path, text)).server()
    assert profile.ssh_target().password == "s3cret"


def test_agent_only_profiles_are_valid(tmp_path):
    profile = load_client_config(write_config(tmp_path, MINIMAL)).server()
    target = profile.ssh_target()
    assert target.use_agent is True
    assert target.key_filename is None and target.password is None


def test_an_unknown_passphrase_transport_is_refused(tmp_path):
    text = MINIMAL + 'passphrase_transport = "carrier-pigeon"\n'
    with pytest.raises(ConfigurationError):
        load_client_config(write_config(tmp_path, text))


def test_passphrase_prefers_the_named_environment_variable(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_PASSPHRASE", "from-named-env")
    monkeypatch.setenv("DBS_PASSPHRASE", "from-generic-env")
    text = MINIMAL + 'passphrase_env = "PROJECT_PASSPHRASE"\npassphrase = "literal"\n'
    profile = load_client_config(write_config(tmp_path, text)).server()
    assert resolve_client_passphrase(profile) == "from-named-env"


def test_passphrase_falls_back_to_the_literal_then_the_generic_variable(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("DBS_PASSPHRASE", "from-generic-env")
    literal = load_client_config(
        write_config(tmp_path, MINIMAL + 'passphrase = "literal"\n')
    ).server()
    assert resolve_client_passphrase(literal) == "literal"

    plain = load_client_config(write_config(tmp_path, MINIMAL, name="plain.toml")).server()
    assert resolve_client_passphrase(plain) == "from-generic-env"


def test_a_named_variable_that_is_unset_is_reported(tmp_path, monkeypatch):
    monkeypatch.delenv("ABSENT_PASSPHRASE", raising=False)
    text = MINIMAL + 'passphrase_env = "ABSENT_PASSPHRASE"\n'
    profile = load_client_config(write_config(tmp_path, text)).server()
    with pytest.raises(ConfigurationError) as excinfo:
        resolve_client_passphrase(profile)
    assert "ABSENT_PASSPHRASE" in str(excinfo.value)


def test_a_non_interactive_run_without_a_passphrase_says_what_to_set(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("DBS_PASSPHRASE", raising=False)
    profile = load_client_config(write_config(tmp_path, MINIMAL)).server()
    with pytest.raises(ConfigurationError) as excinfo:
        resolve_client_passphrase(profile, allow_prompt=False)
    assert "passphrase_env" in str(excinfo.value)


def test_a_passphrase_containing_a_line_break_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("DBS_PASSPHRASE", "two\nlines")
    profile = load_client_config(write_config(tmp_path, MINIMAL)).server()
    with pytest.raises(ConfigurationError):
        resolve_client_passphrase(profile, allow_prompt=False)
