from __future__ import annotations

import argparse
import functools
import hashlib
import http.server
import io
import json
import logging
import os
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

ACCOUNT = "dbs-ssh"
PASSWORD = "dbs-ssh-password"
IMAGE_URL = (
    "https://cloud-images.ubuntu.com/minimal/releases/noble/release-20261105/"
    "ubuntu-24.04-minimal-cloudimg-amd64.img"
)
IMAGE_SHA256 = "406630c08b5e545fcc7209854b129d47e3af822db128c9f19336593b5a2d3fe0"
GUEST_GATEWAY = "10.0.2.2"
LOOPBACK = "127.0.0.1"
DISK_SIZE = "24G"
SYSTEM_BUNDLE = "/etc/ssl/certs/ca-certificates.crt"
CLOUD_INIT_DEGRADED = 2
CHUNK = 1024 * 1024
ABOUT = """Virtual machines for the tests that need real servers.

A guest is QEMU on a copy-on-write disk over a cached Ubuntu 24.04 cloud image, with KVM
where the machine has it and software emulation where it does not. cloud-init creates the
account dbs-ssh with a key, a password and sudo that asks for the password. Its SSH port is
forwarded to 127.0.0.1.

DBS_VM_STATE and DBS_VM_CACHE choose the folders, DBS_VM_IMAGE_URL and DBS_VM_IMAGE_SHA256
another image, DBS_VM_ACCEL, DBS_VM_MEMORY and DBS_VM_CPUS the machine, DBS_VM_BOOT_TIMEOUT
the patience, and DBS_VM_PROXY with DBS_VM_CA_BUNDLE an HTTPS proxy the guest goes through.
"""


def cache_dir() -> Path:
    return Path(os.environ.get("DBS_VM_CACHE") or Path.home() / ".cache" / "dbs-vm")


def state_dir() -> Path:
    return Path(os.environ.get("DBS_VM_STATE") or cache_dir() / "guests")


def guest_dir(name: str) -> Path:
    return state_dir() / name


def boot_timeout() -> float:
    return float(os.environ.get("DBS_VM_BOOT_TIMEOUT") or 1500)


def fail(message: str):
    sys.exit(f"vm: {message}")


def digest_of(path: Path) -> str:
    found = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            found.update(chunk)
    return found.hexdigest()


def base_image() -> Path:
    url = os.environ.get("DBS_VM_IMAGE_URL") or IMAGE_URL
    wanted = os.environ.get("DBS_VM_IMAGE_SHA256") or IMAGE_SHA256
    image = cache_dir() / f"{wanted[:16]}-{url.rsplit('/', 1)[-1]}"
    if image.is_file():
        return image
    cache_dir().mkdir(parents=True, exist_ok=True)
    partial = image.with_name(f"{image.name}.{os.getpid()}.partial")
    print(f"vm: downloading {url}", file=sys.stderr)
    with urllib.request.urlopen(url) as response, partial.open("wb") as handle:
        shutil.copyfileobj(response, handle, CHUNK)
    found = digest_of(partial)
    if found != wanted:
        partial.unlink()
        fail(f"{url} has the digest {found}, not {wanted}.")
    partial.rename(image)
    return image


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind((LOOPBACK, 0))
        return probe.getsockname()[1]


def key_pair(comment: str) -> tuple:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = Ed25519PrivateKey.generate()
    private = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.OpenSSH,
        serialization.NoEncryption(),
    ).decode("ascii")
    public = key.public_key().public_bytes(
        serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH
    ).decode("ascii")
    return private, f"{public} {comment}"


def write_private(path: Path, text: str) -> None:
    path.write_text(text, encoding="ascii")
    path.chmod(0o600)


def proxy_settings() -> dict:
    proxy = os.environ.get("DBS_VM_PROXY", "").strip()
    if not proxy:
        return {}
    settings: dict = {
        "apt": {
            "https_proxy": proxy,
            "primary": [{"arches": ["default"], "uri": "https://archive.ubuntu.com/ubuntu"}],
            "security": [{"arches": ["default"], "uri": "https://security.ubuntu.com/ubuntu"}],
        },
        "write_files": [
            {
                "path": "/etc/environment",
                "append": True,
                "content": f"https_proxy={proxy}\nHTTPS_PROXY={proxy}\n",
            }
        ],
    }
    pip = f"[global]\nproxy = {proxy}\n"
    bundle = os.environ.get("DBS_VM_CA_BUNDLE", "").strip()
    if bundle:
        settings["ca_certs"] = {"trusted": [Path(bundle).read_text(encoding="ascii")]}
        pip += f"cert = {SYSTEM_BUNDLE}\n"
    settings["write_files"].append({"path": "/etc/pip.conf", "content": pip})
    return settings


def user_data(name: str, client_public: str, host_private: str, host_public: str) -> str:
    config = {
        "hostname": name,
        "users": [
            {
                "name": ACCOUNT,
                "shell": "/bin/bash",
                "lock_passwd": False,
                "plain_text_passwd": PASSWORD,
                "sudo": "ALL=(ALL) ALL",
                "ssh_authorized_keys": [client_public],
            }
        ],
        "ssh_pwauth": True,
        "ssh_deletekeys": True,
        "ssh_genkeytypes": ["ed25519"],
        "ssh_keys": {"ed25519_private": host_private, "ed25519_public": host_public},
        "package_update": False,
        "runcmd": [["loginctl", "enable-linger", ACCOUNT]],
        **proxy_settings(),
    }
    return "#cloud-config\n" + json.dumps(config, indent=1) + "\n"


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args) -> None:
        return None


class Seed:
    def __init__(self, folder: Path) -> None:
        self.server = http.server.ThreadingHTTPServer(
            (LOOPBACK, 0), functools.partial(QuietHandler, directory=str(folder))
        )
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> "Seed":
        self.thread.start()
        return self

    def __exit__(self, *exc_info) -> None:
        self.server.shutdown()
        self.server.server_close()


def describe(name: str) -> dict:
    try:
        return json.loads((guest_dir(name) / "guest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        fail(f"there is no guest named {name}; start it with: vm.py up {name}")


def running(name: str) -> bool:
    try:
        pid = int((guest_dir(name) / "qemu.pid").read_text().strip())
        os.kill(pid, 0)
    except (OSError, ValueError):
        return False
    return True


def connect(name: str, timeout: float = 20.0):
    import paramiko

    guest = describe(name)
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    client.load_host_keys(guest["known_hosts"])
    client.connect(
        LOOPBACK,
        port=guest["port"],
        username=ACCOUNT,
        key_filename=guest["key"],
        allow_agent=False,
        look_for_keys=False,
        timeout=timeout,
        banner_timeout=timeout,
        auth_timeout=timeout,
    )
    return client


def wait_for_ssh(name: str) -> None:
    logging.getLogger("paramiko").setLevel(logging.CRITICAL)
    deadline = time.monotonic() + boot_timeout()
    while True:
        if not running(name):
            fail(f"{name} stopped while booting; see {guest_dir(name) / 'console.log'}")
        try:
            connect(name, timeout=10.0).close()
            return
        except Exception as exc:
            if time.monotonic() > deadline:
                fail(f"{name} did not answer over SSH in time: {exc}")
            time.sleep(3)


class Discarded:
    def write(self, data: bytes) -> int:
        return len(data)

    def flush(self) -> None:
        return None


def execute(name: str, command: str, *, sudo: bool = False, out=None, err=None) -> int:
    out = out or sys.stdout.buffer
    err = err or sys.stderr.buffer
    client = connect(name)
    try:
        wrapped = f"sudo -S -p '' sh -c {shlex.quote(command)}" if sudo else command
        stdin, stdout, _ = client.exec_command(wrapped)
        if sudo:
            stdin.write(PASSWORD + "\n")
            stdin.flush()
        stdin.channel.shutdown_write()
        relay(stdout.channel, out, err)
        return stdout.channel.recv_exit_status()
    finally:
        client.close()


def relay(channel, out, err) -> None:
    while not channel.exit_status_ready() or channel.recv_ready() or channel.recv_stderr_ready():
        moved = False
        if channel.recv_ready():
            out.write(channel.recv(65536))
            out.flush()
            moved = True
        if channel.recv_stderr_ready():
            err.write(channel.recv_stderr(65536))
            err.flush()
            moved = True
        if not moved:
            time.sleep(0.05)


def must(name: str, command: str, *, sudo: bool = False, quiet: bool = False) -> None:
    sink = Discarded() if quiet else sys.stderr.buffer
    code = execute(name, command, sudo=sudo, out=sink, err=sink)
    if code != 0:
        fail(f"{command!r} exited {code} in {name}")


def settled(name: str) -> None:
    quiet = Discarded()
    code = execute(name, "cloud-init status --wait", out=quiet, err=quiet)
    if code == CLOUD_INIT_DEGRADED:
        execute(name, "cloud-init status --long", out=sys.stderr.buffer)
    elif code != 0:
        execute(name, "cloud-init status --long", out=sys.stderr.buffer)
        fail(f"cloud-init did not finish in {name}; see {guest_dir(name) / 'console.log'}")


def printed(name: str, command: str, *, sudo: bool = False) -> str:
    kept = io.BytesIO()
    code = execute(name, command, sudo=sudo, out=kept)
    if code != 0:
        fail(f"{command!r} exited {code} in {name}")
    return kept.getvalue().decode("utf-8", "replace")


def up(args) -> int:
    name = args.name
    folder = guest_dir(name)
    if folder.exists():
        if running(name):
            print(f"vm: {name} is already running", file=sys.stderr)
            return 0
        shutil.rmtree(folder)
    for tool in ("qemu-system-x86_64", "qemu-img"):
        if shutil.which(tool) is None:
            fail(f"{tool} is not installed; install qemu-system-x86 and qemu-utils.")
    image = base_image()
    folder.mkdir(parents=True)
    seed = folder / "seed"
    seed.mkdir()
    client_private, client_public = key_pair("dbs-test-client")
    host_private, host_public = key_pair(f"dbs-guest-{name}")
    port = args.ssh_port or free_port()
    write_private(folder / "client_key", client_private)
    (folder / "known_hosts").write_text(
        f"[{LOOPBACK}]:{port} {' '.join(host_public.split()[:2])}\n", encoding="ascii"
    )
    (seed / "meta-data").write_text(
        f"instance-id: dbs-{name}-{port}\nlocal-hostname: {name}\n", encoding="ascii"
    )
    (seed / "user-data").write_text(
        user_data(name, client_public, host_private, host_public), encoding="ascii"
    )
    (seed / "vendor-data").write_text("", encoding="ascii")
    disk = folder / "disk.qcow2"
    subprocess.run(
        ["qemu-img", "create", "-q", "-f", "qcow2", "-F", "qcow2", "-b", str(image), str(disk), DISK_SIZE],
        check=True,
    )
    forwards = "".join(
        f",hostfwd=tcp:{LOOPBACK}:{host}-:{guest}" for host, guest in [(port, 22), *args.forward]
    )
    (folder / "guest.json").write_text(
        json.dumps(
            {
                "name": name,
                "port": port,
                "key": str(folder / "client_key"),
                "known_hosts": str(folder / "known_hosts"),
                "forwards": {str(guest): host for host, guest in args.forward},
            }
        ),
        encoding="utf-8",
    )
    with Seed(seed) as served:
        subprocess.run(
            [
                "qemu-system-x86_64",
                "-name", f"dbs-{name}",
                "-machine", f"q35,accel={os.environ.get('DBS_VM_ACCEL') or 'kvm:tcg'}",
                "-cpu", "max",
                "-smp", os.environ.get("DBS_VM_CPUS") or "2",
                "-m", os.environ.get("DBS_VM_MEMORY") or "1536",
                "-drive", f"file={disk},if=virtio,format=qcow2",
                "-netdev", f"user,id=net0{forwards}",
                "-device", "virtio-net-pci,netdev=net0",
                "-smbios", f"type=1,serial=ds=nocloud;s=http://{GUEST_GATEWAY}:{served.port}/",
                "-display", "none",
                "-serial", f"file:{folder / 'console.log'}",
                "-pidfile", str(folder / "qemu.pid"),
                "-daemonize",
            ],
            check=True,
        )
        wait_for_ssh(name)
        settled(name)
    print(f"vm: {name} answers on {LOOPBACK}:{port}", file=sys.stderr)
    return 0


def env(args) -> int:
    guest = describe(args.name)
    prefix = args.prefix
    values = {
        "HOST": LOOPBACK,
        "PORT": guest["port"],
        "USER": ACCOUNT,
        "PASSWORD": PASSWORD,
        "KEY": guest["key"],
        "KNOWN_HOSTS": guest["known_hosts"],
    }
    for key, value in values.items():
        print(f"{prefix}{key}={value}")
    return 0


def run(args) -> int:
    command = " ".join(shlex.quote(part) for part in args.words)
    if not command:
        fail("give the command after --")
    return execute(args.name, command, sudo=args.sudo)


def push(args) -> int:
    source = Path(args.source)
    if not source.exists():
        fail(f"{source} does not exist")
    client = connect(args.name)
    try:
        sftp = client.open_sftp()
        if source.is_file():
            sftp.put(str(source), args.target)
            return 0
        with tempfile.NamedTemporaryFile(suffix=".tar") as packed:
            with tarfile.open(packed.name, "w") as archive:
                archive.add(source, arcname=".")
            carried = f"/tmp/dbs-vm-push-{os.getpid()}.tar"
            sftp.put(packed.name, carried)
    finally:
        client.close()
    target = shlex.quote(args.target)
    must(args.name, f"mkdir -p {target} && tar -xf {carried} -C {target} && rm -f {carried}")
    return 0


def down(args) -> int:
    folder = guest_dir(args.name)
    try:
        pid = int((folder / "qemu.pid").read_text().strip())
        os.kill(pid, signal.SIGTERM)
        for _ in range(100):
            os.kill(pid, 0)
            time.sleep(0.1)
        os.kill(pid, signal.SIGKILL)
    except (OSError, ValueError):
        pass
    shutil.rmtree(folder, ignore_errors=True)
    return 0


def listed(args) -> int:
    if not state_dir().is_dir():
        return 0
    for folder in sorted(state_dir().iterdir()):
        if (folder / "guest.json").is_file():
            guest = describe(folder.name)
            state = "running" if running(folder.name) else "stopped"
            print(f"{folder.name}\t{LOOPBACK}:{guest['port']}\t{state}")
    return 0


def forward(text: str) -> tuple:
    host, _, guest = text.partition(":")
    try:
        return int(host), int(guest)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not HOSTPORT:GUESTPORT") from None


def parser() -> argparse.ArgumentParser:
    found = argparse.ArgumentParser(description=ABOUT, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = found.add_subparsers(dest="command", required=True)
    starting = commands.add_parser("up", help="Boot a guest and wait until it answers over SSH.")
    starting.add_argument("name")
    starting.add_argument("--ssh-port", type=int, default=0, help="The port on 127.0.0.1 for its SSH.")
    starting.add_argument(
        "--forward", type=forward, action="append", default=[], metavar="HOSTPORT:GUESTPORT",
        help="Another port of the guest to reach on 127.0.0.1.",
    )
    starting.set_defaults(handler=up)
    naming = commands.add_parser("env", help="Print KEY=VALUE lines the tests read.")
    naming.add_argument("name")
    naming.add_argument("--prefix", default="DBS_TEST_SSH_")
    naming.set_defaults(handler=env)
    running_in = commands.add_parser("run", help="Run a command in a guest.")
    running_in.add_argument("name")
    running_in.add_argument("--sudo", action="store_true", help="Run it as root.")
    running_in.add_argument("words", nargs="*", metavar="-- COMMAND")
    running_in.set_defaults(handler=run)
    pushing = commands.add_parser("push", help="Copy a file or a folder into a guest.")
    pushing.add_argument("name")
    pushing.add_argument("source")
    pushing.add_argument("target")
    pushing.set_defaults(handler=push)
    stopping = commands.add_parser("down", help="Stop a guest and forget its disk.")
    stopping.add_argument("name")
    stopping.set_defaults(handler=down)
    commands.add_parser("list", help="The guests that exist.").set_defaults(handler=listed)
    return found


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
