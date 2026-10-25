from __future__ import annotations

import errno
import hashlib
import itertools
import logging
import os
import shutil
import stat
import tempfile
from contextlib import contextmanager
from typing import Iterable

logger = logging.getLogger("dbs")

PRIVATE_MODE = 0o600

LINK_UNSUPPORTED = {
    errno.EPERM,
    errno.EACCES,
    errno.EXDEV,
    errno.EMLINK,
    errno.ENOSYS,
    errno.ENOTSUP,
    errno.EOPNOTSUPP,
}


SYNC_UNSUPPORTED = {errno.EINVAL, errno.ENOTSUP, errno.EOPNOTSUPP}

DIGEST_CHUNK = 1024 * 1024


def file_digest(path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(DIGEST_CHUNK), b""):
            digest.update(chunk)
            size += len(chunk)
    return size, digest.hexdigest()


def refuse_existing(path: str) -> None:
    if os.path.lexists(path):
        raise FileExistsError(errno.EEXIST, "a file already exists at this path", path)


def write_new_file(path: str, data: bytes, verify=None, *, reserved: bool = False) -> None:
    with create_new_file(path, verify, reserved=reserved) as fh:
        fh.write(data)


@contextmanager
def create_new_file(path: str, verify=None, *, reserved: bool = False):
    if not reserved:
        refuse_existing(path)
    directory = os.path.dirname(os.path.abspath(path))
    descriptor, partial = tempfile.mkstemp(
        dir=directory, prefix=f".{os.path.basename(path)}.", suffix=".partial"
    )
    try:
        with os.fdopen(descriptor, "wb") as fh:
            os.fchmod(fh.fileno(), PRIVATE_MODE)
            yield fh
            fh.flush()
            os.fsync(fh.fileno())
        if verify is not None:
            verify(partial)
        if reserved:
            release_reservation(path)
        publish_new(partial, path)
    finally:
        try:
            os.unlink(partial)
        except FileNotFoundError:
            pass


def release_reservation(path: str) -> None:
    try:
        found = os.lstat(path)
    except FileNotFoundError:
        return
    if not stat.S_ISREG(found.st_mode) or found.st_size:
        raise FileExistsError(errno.EEXIST, "a file already exists at this path", path)
    os.unlink(path)


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
    if os.name != "posix":
        return
    try:
        descriptor = os.open(directory, os.O_RDONLY)
    except OSError as exc:
        logger.warning("could not open %s to make its new entries durable: %s", directory, exc)
        return
    try:
        os.fsync(descriptor)
    except OSError as exc:
        if exc.errno not in SYNC_UNSUPPORTED:
            logger.warning("could not make the new entries in %s durable: %s", directory, exc)
    finally:
        os.close(descriptor)


def write_atomic(path: str, data: bytes) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    prefix = f".{os.path.basename(path)}."
    descriptor, partial = tempfile.mkstemp(dir=directory, prefix=prefix)
    try:
        os.fchmod(descriptor, PRIVATE_MODE)
        with os.fdopen(descriptor, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(partial, path)
        os.chmod(path, PRIVATE_MODE)
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


def write_new(data: bytes, destinations: Iterable[str], verify=None) -> str:
    names = iter(destinations)
    first = next(names)
    directory = os.path.dirname(os.path.abspath(first))
    descriptor, partial = tempfile.mkstemp(
        dir=directory, prefix=f".{os.path.basename(first)}.", suffix=".part"
    )
    try:
        os.fchmod(descriptor, PRIVATE_MODE)
        with os.fdopen(descriptor, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        if verify is not None:
            with open(partial, "rb") as fh:
                verify(fh.read())
        for destination in itertools.chain((first,), names):
            if _claim(partial, destination, data):
                return destination
    finally:
        try:
            os.unlink(partial)
        except FileNotFoundError:
            pass
    raise FileExistsError(first)


def _claim(partial: str, destination: str, data: bytes) -> bool:
    try:
        os.link(partial, destination)
    except FileExistsError:
        return False
    except OSError:
        return _write_exclusive(destination, data)
    return True


def _write_exclusive(destination: str, data: bytes) -> bool:
    try:
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, PRIVATE_MODE)
    except FileExistsError:
        return False
    try:
        with os.fdopen(descriptor, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
    except BaseException:
        os.unlink(destination)
        raise
    return True


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
