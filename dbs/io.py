from __future__ import annotations

import os


def write_atomic(path: str, data: bytes) -> None:
    partial = f"{path}.tmp"
    with open(partial, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(partial, path)
