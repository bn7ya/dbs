from __future__ import annotations

import os
from contextlib import contextmanager

from .pipeline import PrefetchingSource

BYTES_TYPES = (bytes, bytearray, memoryview)


def is_path(value) -> bool:
    return isinstance(value, (str, os.PathLike))


@contextmanager
def opened(data):
    if isinstance(data, BYTES_TYPES):
        yield data
        return
    if is_path(data):
        with open(data, "rb") as handle:
            yield handle
        return
    position = _position(data)
    try:
        yield data
    finally:
        if position is not None:
            try:
                data.seek(position)
            except (OSError, ValueError):
                pass


def _position(handle):
    try:
        return handle.tell()
    except (AttributeError, OSError, ValueError):
        return None


def whole(handle) -> bytes:
    if isinstance(handle, BYTES_TYPES):
        return bytes(handle)
    return handle.read()


def stream_source(handle):
    if isinstance(handle, BYTES_TYPES):
        return handle
    return PrefetchingSource(handle)
