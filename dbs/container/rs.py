from __future__ import annotations

import functools
from collections.abc import Sequence

import numpy as np
from reedsolo import RSCodec, ReedSolomonError

CODEWORD_SIZE = 255

PRIMITIVE_POLYNOMIAL = 0x11D

MIN_NSYM = 1

MAX_NSYM = 254

PARITY_BATCH_ROWS = 4096


def _field_tables() -> tuple[list[int], list[int]]:
    exp = [0] * 512
    log = [0] * 256
    value = 1
    for power in range(255):
        exp[power] = value
        log[value] = power
        value <<= 1
        if value & 0x100:
            value ^= PRIMITIVE_POLYNOMIAL
    for power in range(255, 512):
        exp[power] = exp[power - 255]
    return exp, log


_EXP, _LOG = _field_tables()


def _multiply(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _EXP[_LOG[a] + _LOG[b]]


def _generator(nsym: int) -> list[int]:
    poly = [1]
    for power in range(nsym):
        root = _EXP[power]
        product = poly + [0]
        for index, coefficient in enumerate(poly):
            product[index + 1] ^= _multiply(coefficient, root)
        poly = product
    return poly


def _position_remainders(nsym: int) -> list[list[int]]:
    tail = _generator(nsym)[1:]
    remainder = list(tail)
    remainders = [remainder]
    for _ in range(CODEWORD_SIZE - nsym - 1):
        lead = remainder[0]
        remainder = [
            shifted ^ _multiply(lead, coefficient)
            for shifted, coefficient in zip(remainder[1:] + [0], tail)
        ]
        remainders.append(remainder)
    return remainders[::-1]


@functools.lru_cache(maxsize=None)
def _multiplication_table() -> np.ndarray:
    log = np.array(_LOG, dtype=np.intp)
    exp = np.array(_EXP, dtype=np.uint8)
    table = exp[log[:, None] + log[None, :]]
    table[0, :] = 0
    table[:, 0] = 0
    return table


@functools.lru_cache(maxsize=None)
def _parity_table(nsym: int) -> np.ndarray:
    check_nsym(nsym)
    message_len = CODEWORD_SIZE - nsym
    words = (nsym + 7) // 8
    multiplication = _multiplication_table()
    table = np.zeros((message_len, 256, words * 8), dtype=np.uint8)
    for position, remainder in enumerate(_position_remainders(nsym)):
        table[position, :, :nsym] = multiplication[:, np.array(remainder, dtype=np.intp)]
    table.setflags(write=False)
    return table.view(np.uint64).reshape(message_len, 256, words)


@functools.lru_cache(maxsize=None)
def _codec(nsym: int) -> RSCodec:
    return RSCodec(nsym)


def check_nsym(nsym: int) -> None:
    if not isinstance(nsym, int) or not MIN_NSYM <= nsym <= MAX_NSYM:
        raise ValueError(f"nsym must be an integer in [{MIN_NSYM}, {MAX_NSYM}], got {nsym!r}.")


def message_length(nsym: int) -> int:
    return CODEWORD_SIZE - nsym


def encoded_length(data_len: int, nsym: int) -> int:
    full, rest = divmod(data_len, message_length(nsym))
    return full * CODEWORD_SIZE + (rest + nsym if rest else 0)


def codeword_count(encoded_len: int) -> int:
    return -(-encoded_len // CODEWORD_SIZE)


def is_well_formed(encoded_len: int, nsym: int) -> bool:
    rest = encoded_len % CODEWORD_SIZE
    return rest == 0 or rest > nsym


def _parity_rows(messages: np.ndarray, table: np.ndarray) -> np.ndarray:
    accumulator = np.zeros((messages.shape[0], table.shape[2]), dtype=np.uint64)
    gathered = np.empty_like(accumulator)
    columns = np.array(messages.T, dtype=np.intp, order="C")
    for position, column in enumerate(columns):
        np.take(table[position], column, axis=0, out=gathered)
        np.bitwise_xor(accumulator, gathered, out=accumulator)
    return accumulator


def parity(messages: np.ndarray, nsym: int) -> np.ndarray:
    table = _parity_table(nsym)
    count = messages.shape[0]
    if count <= PARITY_BATCH_ROWS:
        return _parity_rows(messages, table).view(np.uint8)[:, :nsym]
    result = np.empty((count, nsym), dtype=np.uint8)
    for start in range(0, count, PARITY_BATCH_ROWS):
        rows = messages[start : start + PARITY_BATCH_ROWS]
        result[start : start + rows.shape[0]] = _parity_rows(rows, table).view(np.uint8)[:, :nsym]
    return result


def _message_rows(data: bytes, nsym: int) -> tuple[np.ndarray, int]:
    message_len = message_length(nsym)
    full, rest = divmod(len(data), message_len)
    rows = np.zeros((full + (1 if rest else 0), message_len), dtype=np.uint8)
    if full:
        rows[:full] = np.frombuffer(data, dtype=np.uint8, count=full * message_len).reshape(
            full, message_len
        )
    if rest:
        rows[full, message_len - rest :] = np.frombuffer(
            data, dtype=np.uint8, offset=full * message_len
        )
    return rows, rest


def encode_many(blocks: Sequence[bytes], nsym: int) -> list[bytes]:
    if not blocks:
        return []
    message_len = message_length(nsym)
    layouts = [_message_rows(bytes(block), nsym) for block in blocks]
    all_parity = parity(np.concatenate([rows for rows, _ in layouts]), nsym)
    encoded: list[bytes] = []
    start = 0
    for (rows, rest), block in zip(layouts, blocks):
        count = rows.shape[0]
        block_parity = all_parity[start : start + count]
        start += count
        full = count - (1 if rest else 0)
        codewords = np.empty((full, CODEWORD_SIZE), dtype=np.uint8)
        codewords[:, :message_len] = rows[:full]
        codewords[:, message_len:] = block_parity[:full]
        tail = b""
        if rest:
            tail = bytes(block[full * message_len :]) + block_parity[full].tobytes()
        encoded.append(codewords.tobytes() + tail)
    return encoded


def encode(data: bytes, nsym: int) -> bytes:
    return encode_many([data], nsym)[0]


def _split(encoded: bytes, nsym: int) -> tuple[np.ndarray, np.ndarray, int]:
    message_len = message_length(nsym)
    full, rest = divmod(len(encoded), CODEWORD_SIZE)
    view = np.frombuffer(encoded, dtype=np.uint8)
    count = full + (1 if rest else 0)
    messages = np.zeros((count, message_len), dtype=np.uint8)
    stored = np.empty((count, nsym), dtype=np.uint8)
    if full:
        codewords = view[: full * CODEWORD_SIZE].reshape(full, CODEWORD_SIZE)
        messages[:full] = codewords[:, :message_len]
        stored[:full] = codewords[:, message_len:]
    if rest:
        tail = view[full * CODEWORD_SIZE :]
        messages[full, message_len - (rest - nsym) :] = tail[: rest - nsym]
        stored[full] = tail[rest - nsym :]
    return messages, stored, rest


def strip_parity(encoded: bytes, nsym: int) -> bytes | None:
    if not is_well_formed(len(encoded), nsym):
        return None
    message_len = message_length(nsym)
    full, rest = divmod(len(encoded), CODEWORD_SIZE)
    view = np.frombuffer(encoded, dtype=np.uint8)
    data = view[: full * CODEWORD_SIZE].reshape(full, CODEWORD_SIZE)[:, :message_len].tobytes()
    if rest:
        data += bytes(encoded[full * CODEWORD_SIZE : len(encoded) - nsym])
    return data


def damaged_codewords(encoded: bytes, nsym: int) -> list[int] | None:
    if not is_well_formed(len(encoded), nsym):
        return None
    messages, stored, _ = _split(encoded, nsym)
    mismatch = np.any(parity(messages, nsym) != stored, axis=1)
    return [int(index) for index in np.flatnonzero(mismatch)]


def codeword(encoded: bytes, index: int) -> bytes:
    return bytes(encoded[index * CODEWORD_SIZE : (index + 1) * CODEWORD_SIZE])


def decode_codeword(codeword_bytes: bytes, nsym: int, erasures=None) -> bytes | None:
    codec = _codec(nsym)
    try:
        if erasures:
            decoded = codec.decode(codeword_bytes, erase_pos=list(erasures))
        else:
            decoded = codec.decode(codeword_bytes)
    except ReedSolomonError:
        return None
    except Exception:
        return None
    return bytes(decoded[0]) if isinstance(decoded, tuple) else bytes(decoded)


def decode_whole(encoded: bytes, nsym: int) -> bytes | None:
    try:
        decoded = _codec(nsym).decode(encoded)
    except ReedSolomonError:
        return None
    except Exception:
        return None
    return bytes(decoded[0]) if isinstance(decoded, tuple) else bytes(decoded)


def decode(encoded: bytes, nsym: int) -> bytes | None:
    damaged = damaged_codewords(encoded, nsym)
    if damaged is None:
        return decode_whole(encoded, nsym)
    data = strip_parity(encoded, nsym)
    if not damaged:
        return data
    message_len = message_length(nsym)
    pieces = bytearray(data)
    for index in damaged:
        repaired = decode_codeword(codeword(encoded, index), nsym)
        if repaired is None:
            return None
        start = index * message_len
        pieces[start : start + len(repaired)] = repaired
    return bytes(pieces)


def _decode_any(codewords: list[bytes], nsym: int) -> tuple[int | None, bytes | None]:
    for source, candidate in enumerate(codewords):
        piece = decode_codeword(candidate, nsym)
        if piece is not None:
            return source, piece
    if len(codewords) == 2 and len(codewords[0]) == len(codewords[1]):
        first, second = codewords
        differing = [position for position, (a, b) in enumerate(zip(first, second)) if a != b]
        if 0 < len(differing) <= nsym:
            for source, candidate in enumerate(codewords):
                piece = decode_codeword(candidate, nsym, differing)
                if piece is not None:
                    return source, piece
    return None, None


def repair_from_copies(
    copies: Sequence[bytes], nsym: int
) -> tuple[bytes | None, set[int], bool]:
    if not copies:
        return None, set(), False
    length = len(copies[0])
    if any(len(copy) != length for copy in copies) or not is_well_formed(length, nsym):
        return None, set(), False
    message_len = message_length(nsym)
    consistent = []
    for copy in copies:
        messages, stored, _ = _split(copy, nsym)
        consistent.append(np.all(parity(messages, nsym) == stored, axis=1))
    stripped = [strip_parity(copy, nsym) for copy in copies]
    repaired = bytearray(stripped[0])
    used: set[int] = set()
    decoded = False
    for index in range(codeword_count(length)):
        start = index * message_len
        source = next(
            (number for number, mask in enumerate(consistent) if mask[index]), None
        )
        if source is not None:
            piece = stripped[source][start : start + message_len]
        else:
            source, piece = _decode_any([codeword(copy, index) for copy in copies], nsym)
            if piece is None:
                return None, used, decoded
            decoded = True
        used.add(source)
        repaired[start : start + len(piece)] = piece
    return bytes(repaired), used, decoded
