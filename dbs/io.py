from __future__ import annotations

import itertools
import os
import tempfile
from typing import Iterable

PRIVATE_MODE = 0o600


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
