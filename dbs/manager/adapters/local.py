from __future__ import annotations

import os
from pathlib import Path
from typing import BinaryIO

PRIVATE_FILE_MODE = 0o600


def private_file(target: Path) -> BinaryIO:
    created = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, PRIVATE_FILE_MODE)
    return os.fdopen(created, "wb")
