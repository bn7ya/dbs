from __future__ import annotations

import hashlib
import json
import os
import zlib

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from dbs.container import DEFAULT_BLOCK_SIZE, DEFAULT_NSYM, BlockPlan, rs
from dbs.container.blocks import _hash
from dbs.container.format import (
    FLAG_COMPRESSED,
    FLAG_ENCRYPTED,
    FLAG_FEC,
    FORMAT_VERSION,
    HEADER_SIZE,
    HEADER_STRUCT,
    MAGIC,
    _manifest_hash,
)
from dbs.crypto.envelope import _DATA_AAD, _DEK_AAD, NONCE_LENGTH, EnvelopeMaterial, _as_bytes
from dbs.crypto.kdf import SALT_LENGTH, KDFParams, derive_key
from dbs.engine.payload import _LEN
from dbs.engine.payload import MAGIC as PAYLOAD_MAGIC
from tests.payloads import read_payload
from tests.conftest import FAST_KDF

ENCODE_GROUP_BLOCKS = 16


def _pack_header(
    *, flags: int, block_size: int, manifest_offset: int, manifest_len: int,
    manifest_dup_offset: int, manifest_hash: bytes,
) -> bytes:
    return HEADER_STRUCT.pack(
        MAGIC,
        FORMAT_VERSION,
        flags,
        block_size,
        manifest_offset,
        manifest_len,
        manifest_dup_offset,
        manifest_hash,
    )


def write_container(manifest: dict, copy_a: bytes, copy_b: bytes, *, flags: int) -> bytes:
    manifest_bytes = json.dumps(manifest, separators=(",", ":")).encode("utf-8")
    manifest_len = len(manifest_bytes)
    manifest_offset = HEADER_SIZE
    manifest_dup_offset = manifest_offset + manifest_len

    header = _pack_header(
        flags=flags,
        block_size=int(manifest["blocks"]["block_size"]),
        manifest_offset=manifest_offset,
        manifest_len=manifest_len,
        manifest_dup_offset=manifest_dup_offset,
        manifest_hash=_manifest_hash(manifest_bytes),
    )

    return b"".join(
        [
            header,
            manifest_bytes,
            manifest_bytes,
            copy_a,
            copy_b,
            header,
        ]
    )


def encode_copy(
    ciphertext: bytes,
    block_size: int = DEFAULT_BLOCK_SIZE,
    nsym: int = DEFAULT_NSYM,
) -> tuple[bytes, BlockPlan]:
    rs.check_nsym(nsym)
    plan = BlockPlan(block_size=block_size, nsym=nsym, ciphertext_len=len(ciphertext))
    parts: list[bytes] = []
    group_span = block_size * ENCODE_GROUP_BLOCKS
    for group_start in range(0, len(ciphertext), group_span):
        group_end = min(group_start + group_span, len(ciphertext))
        group = [
            ciphertext[offset : offset + block_size]
            for offset in range(group_start, group_end, block_size)
        ]
        for block, encoded in zip(group, rs.encode_many(group, nsym)):
            parts.append(encoded)
            plan.enc_lens.append(len(encoded))
            plan.enc_hashes.append(_hash(encoded))
            plan.data_hashes.append(_hash(block))
    return b"".join(parts), plan


def pack_payload(doc_meta, records, files):
    blob_parts: list[bytes] = []
    files_meta: list[dict] = []
    offset = 0
    for entry, data in files:
        entry.offset = offset
        entry.length = len(data)
        offset += len(data)
        files_meta.append(entry.to_dict())
        blob_parts.append(data)

    document = dict(doc_meta)
    document["records"] = records
    document["files"] = files_meta
    json_bytes = json.dumps(document, default=str).encode("utf-8")

    return b"".join([PAYLOAD_MAGIC, _LEN.pack(len(json_bytes)), json_bytes, *blob_parts])


def generate_dek() -> bytes:
    return AESGCM.generate_key(bit_length=256)


def encrypt_payload(
    plaintext,
    passphrase,
    *,
    kdf_params=None,
):
    params = kdf_params or KDFParams()
    salt = os.urandom(SALT_LENGTH)
    kek = derive_key(_as_bytes(passphrase), salt, params)

    dek = generate_dek()
    data_nonce = os.urandom(NONCE_LENGTH)
    ciphertext = AESGCM(dek).encrypt(data_nonce, plaintext, _DATA_AAD)

    dek_nonce = os.urandom(NONCE_LENGTH)
    wrapped_dek = AESGCM(kek).encrypt(dek_nonce, dek, _DEK_AAD)

    material = EnvelopeMaterial(
        salt=salt,
        kdf_params=params,
        wrapped_dek=wrapped_dek,
        dek_nonce=dek_nonce,
        data_nonce=data_nonce,
    )
    return ciphertext, material


def format1_container(
    passphrase,
    document,
    records,
    files,
    *,
    kdf_params=FAST_KDF,
    compress=True,
    block_size=DEFAULT_BLOCK_SIZE,
    nsym=DEFAULT_NSYM,
):
    meta = {key: value for key, value in document.items() if key not in ("records", "files")}
    meta["version"] = 1
    payload = pack_payload(meta, records, files)
    body = zlib.compress(payload, 6) if compress else payload
    ciphertext, material = encrypt_payload(body, passphrase, kdf_params=kdf_params)
    encoded, plan = encode_copy(ciphertext, block_size=block_size, nsym=nsym)
    manifest = {
        "format": "DBS",
        "version": 1,
        "created": meta.get("created"),
        "compression": "zlib" if compress else None,
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
        "copy_len": plan.copy_len,
        "blocks": plan.to_dict(),
        "crypto": material.to_dict(),
    }
    flags = FLAG_ENCRYPTED | FLAG_FEC | (FLAG_COMPRESSED if compress else 0)
    return write_container(manifest, encoded, encoded, flags=flags)


def as_format1(container, passphrase, *, edit=None, **options):
    result = read_payload(container, passphrase)
    document, records, files = result.document, result.records, result.files
    if edit is not None:
        document, records, files = edit(document, records, files)
    return format1_container(passphrase, document, records, files, **options)
