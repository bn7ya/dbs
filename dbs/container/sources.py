from __future__ import annotations

import io
import os

from ..exceptions import ContainerError


class ByteSource:
    def __init__(self, data):
        self._data = memoryview(data).cast("B")
        self.size = len(self._data)

    def read_at(self, offset: int, length: int) -> bytes:
        if offset < 0 or length <= 0 or offset >= self.size:
            return b""
        return bytes(self._data[offset : offset + length])


class FileSource:
    def __init__(self, fileobj):
        self._file = fileobj
        try:
            self._origin = fileobj.tell()
            fileobj.seek(0, io.SEEK_END)
            self.size = fileobj.tell() - self._origin
        except (AttributeError, OSError, ValueError) as exc:
            raise ContainerError(
                "Reading a container needs a readable, seekable binary file."
            ) from exc

    def rewind(self) -> None:
        try:
            self._file.seek(self._origin)
        except (OSError, ValueError):
            pass

    def read_at(self, offset: int, length: int) -> bytes:
        if offset < 0 or length <= 0 or offset >= self.size:
            return b""
        length = min(length, self.size - offset)
        try:
            self._file.seek(self._origin + offset)
            parts = []
            remaining = length
            while remaining:
                piece = self._file.read(remaining)
                if not piece:
                    break
                if not isinstance(piece, (bytes, bytearray)):
                    raise ContainerError(
                        "Reading a container needs a binary file, not a text one."
                    )
                parts.append(piece)
                remaining -= len(piece)
        except (OSError, ValueError) as exc:
            raise ContainerError(f"Could not read the container: {exc}") from exc
        return b"".join(parts)


def as_source(obj):
    if isinstance(obj, (ByteSource, FileSource)):
        return obj
    if isinstance(obj, (bytes, bytearray, memoryview)):
        return ByteSource(obj)
    if isinstance(obj, (str, os.PathLike)):
        raise ContainerError("Pass an open binary file or bytes, not a path.")
    return FileSource(obj)
