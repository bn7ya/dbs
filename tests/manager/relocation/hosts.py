from __future__ import annotations

import hashlib
import io
import os
import tarfile
from pathlib import Path

SUDO = ("sudo", "-n", "-k", "--")


def unwrap(argv):
    argv = list(argv)
    if argv[:2] == ["timeout", "-k"]:
        argv = argv[4:]
    if argv[:4] == list(SUDO):
        argv = argv[4:]
    elif argv[:2] == ["sudo", "-S"]:
        argv = argv[argv.index("--") + 1 :]
    return argv


def archived(folder: Path, excludes=(), member: str | None = None) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        if member is not None:
            archive.add(folder / member, arcname=member)
        else:
            skipped = {str(folder / item) for item in excludes}
            archive.add(
                folder,
                arcname=".",
                filter=lambda info: None
                if any(str(folder / info.name).startswith(skip) for skip in skipped)
                else info,
            )
    return buffer.getvalue()


class LocalSource:
    def __init__(self):
        self.reads = []

    def __call__(self, argv, line):
        argv = unwrap(argv)
        self.reads.append(argv)
        if argv[:2] == ["tar", "--create"]:
            folder = Path(argv[argv.index("--directory") + 1])
            rest = argv[argv.index("--") + 1 :]
            excludes = [item[len("--exclude=./") :] for item in argv if item.startswith("--exclude=./")]
            member = None if rest == ["."] else rest[0]
            return 0, archived(folder, excludes, member), ""
        if argv[1:2] == ["save"]:
            return 0, b"IMAGE:" + argv[2].encode(), ""
        return 127, b"", f"{argv[0]}: not found"


class LocalTarget:
    def __init__(self, *, digest_fails: int = 0, image_id: str = "sha256:abc"):
        self.ran = []
        self.digest_fails = digest_fails
        self.image_id = image_id
        self.loaded = []
        self.volumes = {}

    def __call__(self, argv, line):
        original = list(argv)
        argv = unwrap(argv)
        self.ran.append({"argv": argv, "line": line, "sudo": original[:1] == ["sudo"]})
        name = argv[0]
        if name == "true":
            return 0, "", ""
        if name == "sha256sum":
            data = Path(argv[-1]).read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            if self.digest_fails:
                self.digest_fails -= 1
                digest = "0" * 64
            return 0, f"{digest}  {argv[-1]}\n", ""
        if name == "install" and argv[1] == "-d":
            os.makedirs(argv[-1], exist_ok=True)
            return 0, "", ""
        if name == "tar" and argv[1] == "--extract":
            into = Path(argv[argv.index("--directory") + 1])
            with tarfile.open(argv[argv.index("--file") + 1]) as archive:
                archive.extractall(into, filter="data")
            return 0, "", ""
        if name == "mv":
            source, destination = argv[-2], argv[-1]
            if os.path.lexists(destination):
                return 0, "", ""
            os.rename(source, destination)
            return 0, "", ""
        if name == "rmdir":
            os.rmdir(argv[-1])
            return 0, "", ""
        if name in ("chown", "restorecon"):
            return 0, "", ""
        if name in ("docker", "podman"):
            if argv[1] == "load":
                self.loaded.append(Path(argv[-1]).read_bytes())
                return 0, "Loaded image\n", ""
            if argv[1:3] == ["image", "inspect"]:
                return 0, f"{self.image_id} 1024 amd64\n", ""
            if argv[1:3] == ["volume", "create"]:
                folder = Path(self.root) / "volumes" / argv[-1]
                folder.mkdir(parents=True)
                self.volumes[argv[-1]] = folder
                return 0, f"{argv[-1]}\n", ""
            if argv[1:3] == ["volume", "inspect"]:
                return 0, f"{self.volumes[argv[-1]]}\n", ""
        return 127, "", f"{name}: not found"

    root = "/"
