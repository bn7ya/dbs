from __future__ import annotations

import getpass
import os
import sys
from dataclasses import dataclass, field, fields

from ..exceptions import ConfigurationError
from ..naming import DEFAULT_PREFIX
from ..transports.ssh import SSHTarget

ENV_CONFIG_PATH = "DBS_CLIENT_CONFIG"
ENV_PASSPHRASE = "DBS_PASSPHRASE"

SEARCH_PATHS = ("dbs-client.toml", "~/.config/dbs/client.toml")

SECRET_KEYS = ("password", "passphrase", "key_passphrase")

SSH_KEYS = (
    "host",
    "username",
    "port",
    "key_filename",
    "key_passphrase",
    "password",
    "known_hosts",
    "auto_add_host_key",
    "use_agent",
    "connect_timeout",
    "remote_dir",
)

TRANSPORTS = ("stdin", "env")


def _load_toml(path: str) -> dict:
    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib
        except ImportError as exc:
            raise ConfigurationError(
                'Reading the client config needs a TOML parser: '
                'pip install "django-dbs[client]"'
            ) from exc
    with open(path, "rb") as fh:
        return tomllib.load(fh)


@dataclass
class ServerProfile:
    """Everything needed to reach one server and take a backup from it."""

    name: str
    host: str
    username: str
    port: int = 22
    key_filename: str | None = None
    key_passphrase: str | None = None
    key_passphrase_env: str | None = None
    password: str | None = None
    password_env: str | None = None
    known_hosts: str | None = None
    auto_add_host_key: bool = False
    use_agent: bool = True
    connect_timeout: float = 30.0
    remote_dir: str = "."
    project_dir: str | None = None
    python: str = "python"
    manage: str = "manage.py"
    django_settings_module: str | None = None
    env: dict = field(default_factory=dict)
    passphrase: str | None = None
    passphrase_env: str | None = None
    passphrase_transport: str = "stdin"
    database: str = "default"
    dest: str | None = None
    prefix: str = DEFAULT_PREFIX
    keep: int | None = None
    keep_remote: int | None = None
    interval: str | None = None
    exec_timeout: float | None = None

    def __post_init__(self):
        if self.passphrase_transport not in TRANSPORTS:
            raise ConfigurationError(
                f"Server {self.name!r} has passphrase_transport="
                f"{self.passphrase_transport!r}; use 'stdin' or 'env'."
            )

    def ssh_target(self) -> SSHTarget:
        data = {key: getattr(self, key) for key in SSH_KEYS}
        data["key_passphrase_env"] = self.key_passphrase_env
        data["password_env"] = self.password_env
        return SSHTarget.from_dict({k: v for k, v in data.items() if v is not None})

    def local_dir(self) -> str:
        return os.path.expanduser(self.dest or ".")


@dataclass
class ClientConfig:
    """A parsed client config file and the server profiles it defines."""

    path: str | None
    defaults: dict = field(default_factory=dict)
    servers: dict = field(default_factory=dict)

    def server(self, name: str | None = None) -> ServerProfile:
        if not self.servers:
            raise ConfigurationError(
                f"No servers defined in {self.path or 'the client config'}."
            )
        chosen = name or self.defaults.get("server")
        if chosen is None:
            if len(self.servers) == 1:
                return next(iter(self.servers.values()))
            raise ConfigurationError(
                "Several servers are defined; pick one with --server. "
                f"Available: {', '.join(sorted(self.servers))}."
            )
        try:
            return self.servers[chosen]
        except KeyError:
            raise ConfigurationError(
                f"No server named {chosen!r}. "
                f"Available: {', '.join(sorted(self.servers))}."
            ) from None


def default_config_path() -> str | None:
    from_env = os.environ.get(ENV_CONFIG_PATH)
    if from_env:
        return os.path.expanduser(from_env)
    for candidate in SEARCH_PATHS:
        expanded = os.path.expanduser(candidate)
        if os.path.exists(expanded):
            return expanded
    return None


def load_client_config(path: str | None = None) -> ClientConfig:
    """Read a client config file, returning its defaults and server profiles."""
    resolved = os.path.expanduser(path) if path else default_config_path()
    if resolved is None:
        raise ConfigurationError(
            "No client config found. Run 'dbs-client init' to write one, or pass "
            "--config."
        )
    if not os.path.exists(resolved):
        raise ConfigurationError(f"No client config at {resolved}.")

    document = _load_toml(resolved)
    unknown = set(document) - {"defaults", "servers"}
    if unknown:
        raise ConfigurationError(
            f"Unknown top-level keys in {resolved}: {', '.join(sorted(unknown))}."
        )

    defaults = document.get("defaults", {}) or {}
    raw_servers = document.get("servers", {}) or {}
    _check_permissions(resolved, document)

    known = {item.name for item in fields(ServerProfile)} - {"name"}
    unknown_defaults = set(defaults) - known - {"server"}
    if unknown_defaults:
        raise ConfigurationError(
            f"Unknown keys under [defaults]: {', '.join(sorted(unknown_defaults))}."
        )

    servers = {}
    for name, values in raw_servers.items():
        servers[name] = _build_profile(name, values, defaults, known, resolved)
    return ClientConfig(path=resolved, defaults=defaults, servers=servers)


def resolve_client_passphrase(
    profile: ServerProfile, *, allow_prompt: bool = True
) -> str:
    passphrase = None
    if profile.passphrase_env:
        passphrase = os.environ.get(profile.passphrase_env)
        if not passphrase:
            raise ConfigurationError(
                f"Server {profile.name!r} reads its passphrase from "
                f"${profile.passphrase_env}, which is not set."
            )
    elif profile.passphrase:
        passphrase = profile.passphrase
    else:
        passphrase = os.environ.get(ENV_PASSPHRASE)

    if not passphrase and allow_prompt and sys.stdin.isatty():
        passphrase = getpass.getpass(f"DBS passphrase for {profile.name}: ")
    if not passphrase:
        raise ConfigurationError(
            f"No passphrase for {profile.name!r}. Set passphrase_env or passphrase "
            f"in the config, or export ${ENV_PASSPHRASE}."
        )
    if "\n" in passphrase or "\r" in passphrase:
        raise ConfigurationError("A passphrase cannot contain a line break.")
    return passphrase


def _build_profile(name, values, defaults, known, config_path) -> ServerProfile:
    if not isinstance(values, dict):
        raise ConfigurationError(f"[servers.{name}] must be a table.")
    unknown = set(values) - known
    if unknown:
        raise ConfigurationError(
            f"Unknown keys in [servers.{name}]: {', '.join(sorted(unknown))}."
        )
    merged = {key: value for key, value in defaults.items() if key in known}
    merged.update(values)
    for required in ("host", "username"):
        if not merged.get(required):
            raise ConfigurationError(
                f"[servers.{name}] in {config_path} is missing {required!r}."
            )
    return ServerProfile(name=name, **merged)


def _check_permissions(path: str, document: dict) -> None:
    if os.name != "posix":
        return
    mode = os.stat(path).st_mode
    if mode & 0o022:
        raise ConfigurationError(
            f"{path} is writable by other users; it chooses the remote command and "
            "the host key policy. Run: chmod 600 " + path
        )
    if mode & 0o077 and _holds_a_secret(document):
        raise ConfigurationError(
            f"{path} contains a literal secret and is readable by other users. "
            "Run: chmod 600 " + path
        )


def _holds_a_secret(node) -> bool:
    if isinstance(node, dict):
        for key, value in node.items():
            if key in SECRET_KEYS and value:
                return True
            if _holds_a_secret(value):
                return True
    return False
