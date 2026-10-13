from __future__ import annotations

import errno
import os
import shutil
import tempfile
from contextlib import contextmanager

LINK_UNSUPPORTED = {
    errno.EPERM,
    errno.EACCES,
    errno.EXDEV,
    errno.EMLINK,
    errno.ENOSYS,
    errno.ENOTSUP,
    errno.EOPNOTSUPP,
}


def refuse_existing(path: str) -> None:
    if os.path.lexists(path):
        raise FileExistsError(errno.EEXIST, "a file already exists at this path", path)


def write_new_file(path: str, data: bytes, verify=None) -> None:
    with create_new_file(path, verify) as fh:
        fh.write(data)


@contextmanager
def create_new_file(path: str, verify=None):
    refuse_existing(path)
    directory = os.path.dirname(os.path.abspath(path))
    descriptor, partial = tempfile.mkstemp(
        dir=directory, prefix=f".{os.path.basename(path)}.", suffix=".partial"
    )
    try:
        with os.fdopen(descriptor, "wb") as fh:
            os.fchmod(fh.fileno(), 0o600)
            yield fh
            fh.flush()
            os.fsync(fh.fileno())
        if verify is not None:
            verify(partial)
        publish_new(partial, path)
    finally:
        try:
            os.unlink(partial)
        except FileNotFoundError:
            pass


def publish_new(source: str, destination: str) -> None:
    try:
        os.link(source, destination)
    except FileExistsError:
        raise
    except (AttributeError, NotImplementedError):
        _copy_exclusive(source, destination)
    except OSError as exc:
        if exc.errno not in LINK_UNSUPPORTED:
            raise
        _copy_exclusive(source, destination)
    sync_directory(os.path.dirname(os.path.abspath(destination)))


def _copy_exclusive(source: str, destination: str) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(destination, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as target, open(source, "rb") as origin:
            shutil.copyfileobj(origin, target)
            target.flush()
            os.fsync(target.fileno())
    except BaseException:
        os.unlink(destination)
        raise


def sync_directory(directory: str) -> None:
    try:
        descriptor = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def write_atomic(path: str, data: bytes) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    prefix = f".{os.path.basename(path)}."
    descriptor, partial = tempfile.mkstemp(dir=directory, prefix=prefix)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(partial, path)
        os.chmod(path, 0o600)
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        try:
            os.unlink(partial)
        except FileNotFoundError:
            pass
        raise


def nearest_existing(path: str) -> str:
    probe = os.path.abspath(path)
    while not os.path.exists(probe):
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
    return probe


def can_write_into(directory: str) -> bool:
    probe = nearest_existing(directory)
    return os.path.isdir(probe) and os.access(probe, os.W_OK | os.X_OK)
