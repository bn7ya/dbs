from __future__ import annotations

import os
import tempfile


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
