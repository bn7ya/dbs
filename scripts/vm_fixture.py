from __future__ import annotations

import argparse
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY / "scripts"))

import vm

ABOUT = """Guests prepared for the tests that need real servers.

Each role boots what it needs with scripts/vm.py, carries this checkout's wheel into the
guest and prints the KEY=VALUE lines its tests read:

  ssh                 one guest for tests/test_ssh_openssh.py
  move                a guest with a Django project and a bare one, for the server move in
                      tests/manager/live/test_relocation.py
  containers ENGINE   a guest running the Compose project with docker or podman, for
                      tests/manager/live/test_containers.py
  e2e                 a guest with the projects and the Compose service of the Playwright
                      journeys; --mount DIR also mounts its files there with sshfs
  down                stops every guest
"""
WHEELHOUSE = "/opt/dbs-wheelhouse"
FIXTURE = "/opt/dbs-fixture"
PROJECTS = "/srv/e2e"
LIVE = "/srv/dbs-live"
CARRIED = ("scripts/e2e_fixture.sh", "scripts/container_fixture.sh", "tests/containers/project")
PROJECT_PACKAGES = ("python3-venv",)
ENGINE_PACKAGES = {
    "docker": ("docker.io", "docker-compose-v2", "docker-buildx"),
    "podman": ("podman", "podman-compose", "uidmap", "slirp4netns"),
}
GUEST_WHEELS = (
    "--only-binary=:all:",
    "--python-version", "3.12",
    "--implementation", "cp",
    "--abi", "cp312",
    "--abi", "abi3",
    "--abi", "none",
    "--platform", "manylinux2014_x86_64",
    "--platform", "manylinux_2_17_x86_64",
    "--platform", "manylinux_2_27_x86_64",
    "--platform", "manylinux_2_28_x86_64",
)
SSH_PREFIX = "DBS_TEST_SSH_"
TARGET_PREFIX = "DBS_TEST_MOVE_TARGET_"


def note(message: str) -> None:
    print(f"vm: {message}", file=sys.stderr)


def pip(*arguments: str) -> None:
    subprocess.run([sys.executable, "-m", "pip", *arguments], check=True, stdout=sys.stderr)


def wheelhouse(folder: Path, *, dependencies: bool) -> None:
    note("building this checkout's wheel")
    pip("wheel", "--quiet", "--no-deps", "--wheel-dir", str(folder), str(REPOSITORY))
    if dependencies:
        [wheel] = folder.glob("django_dbs-*.whl")
        pip("download", "--quiet", "--dest", str(folder), *GUEST_WHEELS, str(wheel))


def boot(*names: str) -> None:
    vm.base_image()
    starting = [
        subprocess.Popen([sys.executable, vm.__file__, "up", name], stdout=sys.stderr)
        for name in names
    ]
    if any(process.wait() != 0 for process in starting):
        vm.fail(f"could not boot {' and '.join(names)}")


def carried(name: str, source: Path, target: str) -> None:
    folder = shlex.quote(target)
    vm.must(name, f"rm -rf {folder} && install -d -o {vm.ACCOUNT} {folder}", sudo=True)
    vm.push(argparse.Namespace(name=name, source=str(source), target=target))


def installed(name: str, packages: tuple) -> None:
    if not packages:
        return
    note(f"installing {' '.join(packages)} in {name}")
    apt = "DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=300"
    refreshed = f"tries=0; until {apt} update -q; do tries=$((tries + 1)); [ $tries -lt 5 ] || exit 1; sleep 5; done"
    vm.must(name, f"{refreshed}; {apt} install -y -q {' '.join(packages)}", sudo=True)


def prepared(name: str, wheels: Path, packages: tuple = (), *, scripts: bool = True) -> None:
    carried(name, wheels, WHEELHOUSE)
    if scripts:
        with tempfile.TemporaryDirectory() as staging:
            for part in CARRIED:
                destination = Path(staging) / part
                destination.parent.mkdir(parents=True, exist_ok=True)
                if (REPOSITORY / part).is_dir():
                    shutil.copytree(REPOSITORY / part, destination)
                else:
                    shutil.copy2(REPOSITORY / part, destination)
            carried(name, Path(staging), FIXTURE)
    installed(name, packages)


def fixture(name: str, script: str, *arguments: str, **environment: str) -> dict:
    note(f"running {script} in {name}")
    settings = {"DBS_FIXTURE_WHEELHOUSE": WHEELHOUSE, **environment}
    words = [
        "env",
        *(f"{key}={value}" for key, value in settings.items()),
        "sh",
        f"{FIXTURE}/scripts/{script}",
        *arguments,
    ]
    printed = vm.printed(name, " ".join(shlex.quote(word) for word in words), sudo=True)
    return dict(line.split("=", 1) for line in printed.splitlines() if "=" in line)


def reached(name: str) -> dict:
    guest = vm.describe(name)
    return {
        "HOST": vm.LOOPBACK,
        "PORT": str(guest["port"]),
        "USER": vm.ACCOUNT,
        "PASSWORD": vm.PASSWORD,
        "KEY": guest["key"],
        "KNOWN_HOSTS": guest["known_hosts"],
    }


def announce(values: dict, prefix: str = "") -> None:
    for key, value in values.items():
        print(f"{prefix}{key}={value}")


def ssh(args) -> int:
    boot("ssh")
    announce(reached("ssh"), SSH_PREFIX)
    return 0


def move(args) -> int:
    boot("old", "new")
    with tempfile.TemporaryDirectory() as wheels:
        wheelhouse(Path(wheels), dependencies=False)
        prepared("old", Path(wheels), PROJECT_PACKAGES)
        prepared("new", Path(wheels), scripts=False)
    found = fixture("old", "e2e_fixture.sh", PROJECTS, DBS_TEST_SSH_PORT="22")
    announce(reached("old"), SSH_PREFIX)
    target = reached("new")
    target.pop("PASSWORD")
    announce(target, TARGET_PREFIX)
    announce(
        {
            "DBS_TEST_MOVE_PROJECT": found["E2E_SSH_PROJECT_DIR"],
            "DBS_TEST_MOVE_SUDO_PASSWORD": vm.PASSWORD,
        }
    )
    return 0


def containers(args) -> int:
    name = args.engine
    boot(name)
    with tempfile.TemporaryDirectory() as wheels:
        wheelhouse(Path(wheels), dependencies=True)
        prepared(name, Path(wheels), ENGINE_PACKAGES[args.engine])
    found = fixture(name, "container_fixture.sh", args.engine, LIVE)
    announce(reached(name), SSH_PREFIX)
    announce(found)
    return 0


def mounted(name: str, folder: str) -> None:
    if shutil.which("sshfs") is None:
        vm.fail("sshfs is not installed; install it or leave --mount out.")
    guest = vm.describe(name)
    Path(folder).mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "sshfs",
            f"{vm.ACCOUNT}@{vm.LOOPBACK}:/",
            folder,
            "-p", str(guest["port"]),
            "-o", f"IdentityFile={guest['key']}",
            "-o", f"UserKnownHostsFile={guest['known_hosts']}",
            "-o", "StrictHostKeyChecking=yes",
            "-o", "IdentitiesOnly=yes",
            "-o", "reconnect",
            "-o", "dir_cache=no",
        ],
        check=True,
        stdout=sys.stderr,
    )


def e2e(args) -> int:
    boot("e2e")
    with tempfile.TemporaryDirectory() as wheels:
        wheelhouse(Path(wheels), dependencies=True)
        prepared("e2e", Path(wheels), (*PROJECT_PACKAGES, *ENGINE_PACKAGES["docker"]))
    found = fixture("e2e", "e2e_fixture.sh", PROJECTS, "docker", DBS_TEST_SSH_PORT="22", E2E_FIXTURE_SUDO="1")
    guest = reached("e2e")
    found.update({"E2E_SSH_HOST": guest["HOST"], "E2E_SSH_PORT": guest["PORT"], "E2E_SSH_FS": ""})
    if args.mount:
        mounted("e2e", args.mount)
        found["E2E_SSH_FS"] = str(Path(args.mount).resolve())
    announce(found)
    return 0


def unmounted() -> None:
    source = f"{vm.ACCOUNT}@{vm.LOOPBACK}:"
    release = shutil.which("fusermount3") or shutil.which("fusermount")
    mounts = Path("/proc/mounts")
    if release is None or not mounts.is_file():
        return
    for line in mounts.read_text(encoding="utf-8", errors="replace").splitlines():
        device, folder, kind = line.split()[:3]
        if kind == "fuse.sshfs" and device.startswith(source):
            subprocess.run([release, "-u", folder.replace("\\040", " ")], check=False)


def down(args) -> int:
    unmounted()
    if vm.state_dir().is_dir():
        for folder in sorted(vm.state_dir().iterdir()):
            if (folder / "guest.json").is_file():
                vm.down(argparse.Namespace(name=folder.name))
    return 0


def parser() -> argparse.ArgumentParser:
    found = argparse.ArgumentParser(description=ABOUT, formatter_class=argparse.RawDescriptionHelpFormatter)
    roles = found.add_subparsers(dest="role", required=True)
    roles.add_parser("ssh", help="One guest for the SSH transport tests.").set_defaults(handler=ssh)
    roles.add_parser("move", help="Two guests for the server move.").set_defaults(handler=move)
    engines = roles.add_parser("containers", help="A guest running the Compose project.")
    engines.add_argument("engine", choices=sorted(ENGINE_PACKAGES))
    engines.set_defaults(handler=containers)
    journeys = roles.add_parser("e2e", help="A guest for the Playwright journeys.")
    journeys.add_argument("--mount", default="", metavar="DIR", help="Mount the guest's files there with sshfs.")
    journeys.set_defaults(handler=e2e)
    roles.add_parser("down", help="Stop every guest.").set_defaults(handler=down)
    return found


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
