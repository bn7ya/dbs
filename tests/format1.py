import hashlib
import zlib

from dbs.container import DEFAULT_BLOCK_SIZE, DEFAULT_NSYM, encode_copy, write_container
from dbs.container.format import FLAG_COMPRESSED, FLAG_ENCRYPTED, FLAG_FEC
from dbs.crypto import encrypt_payload
from dbs.engine.payload import pack_payload
from dbs.engine.restore import read_payload
from tests.conftest import FAST_KDF


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
