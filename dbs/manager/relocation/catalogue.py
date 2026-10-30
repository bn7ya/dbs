from __future__ import annotations

import posixpath
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from dbs.manager.common.paths import absolute_path
from dbs.manager.redeploy.catalogue import SERVICE_NAME
from dbs.manager.relocation.packages import PACKAGE

IMAGE_REF = re.compile(
    r"^(?:sha256:[0-9a-f]{64}|[A-Za-z0-9][A-Za-z0-9._/:@-]{0,254})$"
)
VOLUME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,254}$")
NETWORK = VOLUME
CONTAINER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,254}$")
UNIT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9@._-]{0,99}\.(service|socket|timer)$")
SITE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
USER = re.compile(r"^[a-z_][a-z0-9_-]{0,31}\$?$")
NUMERIC = re.compile(r"^[0-9]{1,10}$")
MODE = re.compile(r"^0[0-7]{3}$")
MODULE_STREAM = re.compile(r"^[a-z0-9-]+:[0-9]+$")
RELATIVE = re.compile(r"^(?!-)(?!.*(?:^|/)\.\.(?:/|$))[^*?\[\]\n\0]{1,1024}$")
CONTAINER_USER = re.compile(r"^[A-Za-z0-9_.-]{1,64}(?::[A-Za-z0-9_.-]{1,64})?$")
LABEL_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,254}$")
PROTOCOLS = ("tcp", "udp", "sctp")
RESTART_POLICIES = ("no", "always", "unless-stopped", "on-failure")
APT = ("env", "DEBIAN_FRONTEND=noninteractive", "NEEDRESTART_MODE=a", "apt-get")
APT_LOCK = ("-o", "DPkg::Lock::Timeout=300")
SYSTEMCTL_VERBS = frozenset({"daemon-reload", "enable", "is-active", "reload", "restart"})
ROOT = "root"
NOPASSWD = "nopasswd"
PASSWORD = "password"
MISSING = "missing"


@dataclass(frozen=True)
class Command:
    argv: tuple[str, ...]
    cwd: str | None = None
    env: tuple[tuple[str, str], ...] = ()
    root: bool = False
    user: str = ""

    @property
    def environment(self) -> dict[str, str] | None:
        return dict(self.env) if self.env else None


@dataclass(frozen=True)
class Port:
    host_ip: str
    host_port: int
    container_port: int
    protocol: str = "tcp"


@dataclass(frozen=True)
class Mount:
    kind: str
    source: str
    destination: str
    read_only: bool = False


@dataclass(frozen=True)
class ContainerSpec:
    engine: str
    name: str
    image: str
    env_file: str = ""
    ports: tuple[Port, ...] = ()
    mounts: tuple[Mount, ...] = ()
    restart: str = "no"
    restart_retries: int = 0
    network: str = ""
    user: str = ""
    workdir: str = ""
    entrypoint: tuple[str, ...] | None = None
    command: tuple[str, ...] | None = None
    labels: tuple[tuple[str, str], ...] = field(default_factory=tuple)


def path(value: str) -> str:
    cleaned = absolute_path(value)
    if cleaned is None or "\n" in value or "\0" in value:
        raise ValueError(f"Not an absolute path: {value!r}")
    return cleaned


def matched(pattern: re.Pattern[str], value: str, what: str) -> str:
    if not isinstance(value, str) or not pattern.match(value):
        raise ValueError(f"Not a valid {what}: {value!r}")
    return value


def engine(value: str) -> str:
    if value not in ("docker", "podman"):
        raise ValueError(f"Not a container engine: {value!r}")
    return value


def _excludes(excludes: Iterable[str]) -> list[str]:
    return [f"--exclude=./{matched(RELATIVE, item, 'exclusion')}" for item in excludes]


def tar_create(folder: str, excludes: Iterable[str] = (), *, root: bool = False) -> Command:
    return Command(
        (
            "tar",
            "--create",
            "--gzip",
            "--file",
            "-",
            "--anchored",
            "--no-wildcards",
            *_excludes(excludes),
            "--directory",
            path(folder),
            "--",
            ".",
        ),
        root=root,
    )


def tar_create_member(folder: str, name: str, *, root: bool = False) -> Command:
    return Command(
        (
            "tar",
            "--create",
            "--gzip",
            "--file",
            "-",
            "--directory",
            path(folder),
            "--",
            matched(RELATIVE, name, "file name"),
        ),
        root=root,
    )


def tar_extract(archive: str, into: str, *, numeric: bool, root: bool = True) -> Command:
    owners = ("--same-owner",) if root else ("--no-same-owner",)
    return Command(
        (
            "tar",
            "--extract",
            "--gzip",
            "--file",
            path(archive),
            "--directory",
            path(into),
            *owners,
            "--same-permissions",
            "--keep-old-files",
            *(("--numeric-owner",) if numeric and root else ()),
        ),
        root=root,
    )


def uname_machine() -> Command:
    return Command(("uname", "-m"))


def user_ids() -> Command:
    return Command(("id",))


def sudo_present() -> Command:
    return Command(("sudo", "--version"))


def sudo_without_password() -> Command:
    return Command(("sudo", "-n", "-k", "--", "true"))


def sudo_check() -> Command:
    return Command(("true",), root=True)


def free_space(paths: Sequence[str]) -> Command:
    return Command(("df", "-P", "-B1", "--", *(path(item) for item in paths)))


def disk_usage(folder: str, excludes: Iterable[str] = (), *, root: bool = False) -> Command:
    return Command(
        (
            "du",
            "-s",
            "-b",
            "-x",
            *(f"--exclude={posixpath.join(path(folder), matched(RELATIVE, item, 'exclusion'))}" for item in excludes),
            "--",
            path(folder),
        ),
        root=root,
    )


def unreadable(folder: str) -> Command:
    return Command(("find", path(folder), "-xdev", "!", "-readable", "-print", "-quit"))


def listening() -> Command:
    return Command(("ss", "-H", "-t", "-l", "-n"))


def selinux_mode() -> Command:
    return Command(("getenforce",))


def firewall_active() -> Command:
    return Command(("systemctl", "is-active", "firewalld"))


def dpkg_installed(packages: Sequence[str]) -> Command:
    return Command(
        (
            "dpkg-query",
            "-W",
            "-f",
            "${Package}\t${db:Status-Abbrev}\n",
            *(matched(PACKAGE, name, "package") for name in packages),
        )
    )


def rpm_installed(packages: Sequence[str]) -> Command:
    return Command(
        (
            "rpm",
            "-q",
            "--queryformat",
            "%{NAME}\n",
            *(matched(PACKAGE, name, "package") for name in packages),
        )
    )


def apt_update() -> Command:
    return Command((*APT, *APT_LOCK, "update"), root=True)


def apt_install(packages: Sequence[str]) -> Command:
    return Command(
        (
            *APT,
            *APT_LOCK,
            "install",
            "-y",
            "--no-install-recommends",
            *(matched(PACKAGE, name, "package") for name in packages),
        ),
        root=True,
    )


def dnf_install(packages: Sequence[str]) -> Command:
    return Command(
        ("dnf", "install", "-y", *(matched(PACKAGE, name, "package") for name in packages)),
        root=True,
    )


def dnf_module_enable(stream: str) -> Command:
    return Command(
        ("dnf", "module", "enable", "-y", matched(MODULE_STREAM, stream, "module stream")),
        root=True,
    )


def fetch_key(url: str, destination: str) -> Command:
    if not url.startswith("https://download.docker.com/linux/"):
        raise ValueError(f"Not a key this catalogue fetches: {url!r}")
    return Command(
        ("curl", "-fsSL", "--proto", "=https", "--tlsv1.2", "-o", path(destination), url)
    )


def key_fingerprints(key: str, home: str) -> Command:
    return Command(
        ("gpg", "--batch", "--homedir", path(home), "--with-colons", "--show-keys", path(key))
    )


def rpm_import(key: str) -> Command:
    return Command(("rpm", "--import", path(key)), root=True)


def make_folder(folder: str, mode: str, owner: str, group: str) -> Command:
    return Command(
        (
            "install",
            "-d",
            "-m",
            matched(MODE, mode, "mode"),
            "-o",
            matched(NUMERIC, owner, "owner"),
            "-g",
            matched(NUMERIC, group, "group"),
            "--",
            path(folder),
        ),
        root=True,
    )


def copy_new(staged: str, destination: str) -> Command:
    return Command(
        ("cp", "-n", "-T", "--no-preserve=all", "--", path(staged), path(destination)),
        root=True,
    )


def make_readable(file: str) -> Command:
    return Command(("chmod", "0644", "--", path(file)), root=True)


def remove_own_link(link: str) -> Command:
    return Command(("rm", "--", path(link)), root=True)


def network_exists(name: str, network: str) -> Command:
    return Command((engine(name), "network", "inspect", matched(NETWORK, network, "network")))


def link_new(target: str, link: str) -> Command:
    return Command(("ln", "-s", "-T", "--", path(target), path(link)), root=True)


def remove_empty_folder(folder: str, *, root: bool = True) -> Command:
    return Command(("rmdir", "--", path(folder)), root=root)


def place(incoming: str, destination: str, *, root: bool = True) -> Command:
    return Command(("mv", "-T", "-n", "--", path(incoming), path(destination)), root=root)


def own_user(folder: str, from_uid: str, to_uid: str) -> Command:
    return Command(
        (
            "chown",
            "-R",
            "-h",
            f"--from={matched(NUMERIC, from_uid, 'user id')}",
            matched(NUMERIC, to_uid, "user id"),
            "--",
            path(folder),
        ),
        root=True,
    )


def own_group(folder: str, from_gid: str, to_gid: str) -> Command:
    return Command(
        (
            "chown",
            "-R",
            "-h",
            f"--from=:{matched(NUMERIC, from_gid, 'group id')}",
            f":{matched(NUMERIC, to_gid, 'group id')}",
            "--",
            path(folder),
        ),
        root=True,
    )


def restore_contexts(folder: str) -> Command:
    return Command(("restorecon", "-R", "--", path(folder)), root=True)


def sha256(file: str, *, root: bool = False) -> Command:
    return Command(("sha256sum", "--", path(file)), root=root)


def systemctl(verb: str, unit: str = "", *, now: bool = False) -> Command:
    if verb not in SYSTEMCTL_VERBS:
        raise ValueError(f"Not a systemctl verb this catalogue runs: {verb!r}")
    argv = ["systemctl", verb]
    if now:
        argv.append("--now")
    if unit:
        argv.append(matched(UNIT, unit if "." in unit else f"{unit}.service", "unit"))
    return Command(tuple(argv), root=True)


def systemctl_user(verb: str, unit: str, runtime_dir: str, *, now: bool = False) -> Command:
    if verb not in SYSTEMCTL_VERBS:
        raise ValueError(f"Not a systemctl verb this catalogue runs: {verb!r}")
    argv = ["systemctl", "--user", verb]
    if now:
        argv.append("--now")
    if unit:
        argv.append(matched(UNIT, unit, "unit"))
    return Command(tuple(argv), env=(("XDG_RUNTIME_DIR", path(runtime_dir)),))


def enable_linger(user: str) -> Command:
    return Command(("loginctl", "enable-linger", matched(USER, user, "user")), root=True)


def add_to_group(user: str, group: str) -> Command:
    return Command(
        ("usermod", "-aG", matched(USER, group, "group"), matched(USER, user, "user")),
        root=True,
    )


def add_subordinate_ids(user: str, first: int = 100000, count: int = 65536) -> Command:
    span = f"{first}-{first + count - 1}"
    return Command(
        (
            "usermod",
            "--add-subuids",
            span,
            "--add-subgids",
            span,
            matched(USER, user, "user"),
        ),
        root=True,
    )


def add_system_user(user: str) -> Command:
    return Command(
        (
            "useradd",
            "--system",
            "--no-create-home",
            "--shell",
            "/usr/sbin/nologin",
            matched(USER, user, "user"),
        ),
        root=True,
    )


def nginx_test() -> Command:
    return Command(("nginx", "-t"), root=True)


def postgresql_init() -> Command:
    return Command(
        (
            "env",
            "PGSETUP_INITDB_OPTIONS=--auth-host=scram-sha-256 --auth-local=peer",
            "postgresql-setup",
            "--initdb",
        ),
        root=True,
    )


def postgresql_shell() -> Command:
    return Command(("psql", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-d", "postgres"), root=True, user="postgres")


def postgresql_query(sql: str) -> Command:
    return Command(("psql", "-X", "-tA", "-d", "postgres", "-c", sql), root=True, user="postgres")


def mysql_query(sql: str) -> Command:
    return Command(("mysql", "--protocol=socket", "--user=root", "-N", "-e", sql), root=True)


def mysql_shell() -> Command:
    return Command(("mysql", "--protocol=socket", "--user=root", "--batch"), root=True)


def engine_architecture(name: str) -> Command:
    return Command((engine(name), "info", "--format", "{{.Architecture}}"))


def engine_version(name: str) -> Command:
    return Command((engine(name), "version"))


def image_save(name: str, ref: str, *, root: bool = False) -> Command:
    return Command((engine(name), "save", matched(IMAGE_REF, ref, "image")), root=root)


def image_load(name: str, archive: str) -> Command:
    return Command((engine(name), "load", "--input", path(archive)))


def image_facts(name: str, ref: str) -> Command:
    return Command(
        (
            engine(name),
            "image",
            "inspect",
            "--format",
            "{{.Id}} {{.Size}} {{.Architecture}}",
            matched(IMAGE_REF, ref, "image"),
        )
    )


def volume_mountpoint(name: str, volume: str) -> Command:
    return Command(
        (
            engine(name),
            "volume",
            "inspect",
            "--format",
            "{{.Mountpoint}}",
            matched(VOLUME, volume, "volume"),
        )
    )


def volume_create(name: str, volume: str, labels: Mapping[str, str] = {}) -> Command:
    flags = [
        item
        for key, value in sorted(labels.items())
        for item in ("--label", f"{matched(LABEL_KEY, key, 'label')}={_label_value(value)}")
    ]
    return Command(
        (engine(name), "volume", "create", *flags, matched(VOLUME, volume, "volume"))
    )


def volume_export(volume: str) -> Command:
    return Command(("podman", "volume", "export", matched(VOLUME, volume, "volume")))


def volume_import(volume: str, archive: str) -> Command:
    return Command(
        ("podman", "volume", "import", matched(VOLUME, volume, "volume"), path(archive))
    )


def network_create(name: str, network: str) -> Command:
    return Command((engine(name), "network", "create", matched(NETWORK, network, "network")))


def compose_up(compose_argv: Sequence[str], services: Sequence[str], cwd: str) -> Command:
    return Command(
        (
            *compose_argv,
            "up",
            "-d",
            "--no-build",
            *(matched(SERVICE_NAME, service, "service") for service in services),
        ),
        cwd=path(cwd),
    )


def _label_value(value: str) -> str:
    if not isinstance(value, str) or "\n" in value or "\0" in value or len(value) > 1024:
        raise ValueError(f"Not a valid label value: {value!r}")
    return value


def container_run(spec: ContainerSpec) -> Command:
    argv: list[str] = [
        engine(spec.engine),
        "run",
        "--detach",
        "--name",
        matched(CONTAINER, spec.name, "container"),
    ]
    if spec.env_file:
        argv += ["--env-file", path(spec.env_file)]
    for port in spec.ports:
        if port.protocol not in PROTOCOLS or not (
            0 < port.host_port < 65536 and 0 < port.container_port < 65536
        ):
            raise ValueError(f"Not a valid port: {port!r}")
        host = f"{port.host_ip}:" if port.host_ip else ""
        if port.host_ip and not re.match(r"^[0-9a-fA-F.:\[\]]{1,45}$", port.host_ip):
            raise ValueError(f"Not a valid address: {port.host_ip!r}")
        argv += ["--publish", f"{host}{port.host_port}:{port.container_port}/{port.protocol}"]
    for mount in spec.mounts:
        source = (
            path(mount.source)
            if mount.kind == "bind"
            else matched(VOLUME, mount.source, "volume")
        )
        suffix = ":ro" if mount.read_only else ""
        argv += ["--volume", f"{source}:{path(mount.destination)}{suffix}"]
    if spec.restart not in RESTART_POLICIES:
        raise ValueError(f"Not a restart policy: {spec.restart!r}")
    restart = (
        f"on-failure:{spec.restart_retries}"
        if spec.restart == "on-failure" and spec.restart_retries > 0
        else spec.restart
    )
    argv += ["--restart", restart]
    if spec.network:
        argv += ["--network", matched(NETWORK, spec.network, "network")]
    if spec.user:
        argv += ["--user", matched(CONTAINER_USER, spec.user, "user")]
    if spec.workdir:
        argv += ["--workdir", path(spec.workdir)]
    for key, value in spec.labels:
        argv += ["--label", f"{matched(LABEL_KEY, key, 'label')}={_label_value(value)}"]
    entrypoint = list(spec.entrypoint) if spec.entrypoint is not None else None
    if entrypoint is not None:
        argv += ["--entrypoint", entrypoint[0] if entrypoint else ""]
    argv += ["--", matched(IMAGE_REF, spec.image, "image")]
    if entrypoint:
        argv += [_argument(item) for item in entrypoint[1:]]
    if spec.command:
        argv += [_argument(item) for item in spec.command]
    return Command(tuple(argv))


def _argument(value: str) -> str:
    if not isinstance(value, str) or "\0" in value or len(value) > 4096:
        raise ValueError(f"Not a valid argument: {value!r}")
    return value


def pip_freeze(python: str) -> Command:
    return Command((path(python), "-m", "pip", "freeze", "--all", "--exclude-editable"))


def make_venv(python: str, folder: str) -> Command:
    return Command((path(python), "-m", "venv", path(folder)))


def pip_install(python: str, requirements: str, cwd: str) -> Command:
    return Command(
        (path(python), "-m", "pip", "install", "--no-input", "-r", path(requirements)),
        cwd=path(cwd),
    )


def git_head(folder: str) -> Command:
    return Command(("git", "-C", path(folder), "rev-parse", "HEAD"))


def privileged(command: Command, mode: str) -> list[str]:
    argv = list(command.argv)
    if not command.root:
        return argv
    as_user = ["-u", matched(USER, command.user, "user")] if command.user else []
    if mode == ROOT:
        return ["runuser", "-u", command.user, "--", *argv] if command.user else argv
    if mode == NOPASSWD:
        return ["sudo", "-n", "-k", *as_user, "--", *argv]
    if mode == PASSWORD:
        return ["sudo", "-S", "-p", "", "-k", *as_user, "--", *argv]
    raise ValueError(f"No way to run {argv[0]} as root on this server.")


def needs_password_line(argv: Sequence[str]) -> bool:
    return list(argv[:2]) == ["sudo", "-S"]


SOURCE_READS = (
    ("tar", "--create"),
    ("du",),
    ("find",),
    ("df",),
    ("id",),
    ("uname",),
    ("ss",),
    ("getenforce",),
    ("systemctl", "is-active"),
    ("sudo", "--version"),
    ("sudo", "-n", "-k", "--", "true"),
    ("sha256sum",),
    ("git", "-C"),
    ("dpkg-query",),
    ("rpm", "-q"),
)
SOURCE_ENGINE_READS = (
    ("ps",),
    ("inspect",),
    ("info",),
    ("version",),
    ("save",),
    ("image", "inspect"),
    ("volume", "inspect"),
    ("volume", "export"),
    ("compose", "version"),
)
