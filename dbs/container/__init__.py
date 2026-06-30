"""The container layer: block framing, redundancy, Reed-Solomon and file format.

This is the part that makes the backup *self-healing*. The encrypted payload is
split into fixed-size blocks; every block carries its own hash and a layer of
Reed-Solomon parity, and the whole encrypted stream is written twice. On read,
each block is recovered from whichever copy verifies, with Reed-Solomon
correcting the kind of sparse bit-flips a non-ECC RAM stick produces.
"""

from .blocks import (
    DEFAULT_BLOCK_SIZE,
    DEFAULT_NSYM,
    BlockPlan,
    RepairReport,
    encode_copy,
    repair_copies,
)
from .format import read_container, write_container

__all__ = [
    "DEFAULT_BLOCK_SIZE",
    "DEFAULT_NSYM",
    "BlockPlan",
    "RepairReport",
    "encode_copy",
    "repair_copies",
    "read_container",
    "write_container",
]
