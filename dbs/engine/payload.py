from __future__ import annotations

import json
import struct

from ..files import FileEntry

MAGIC = b"DBSPAY01"
_LEN = struct.Struct(">I")


def pack_payload(doc_meta: dict, records: list[dict], files: list[tuple[FileEntry, bytes]]) -> bytes:
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

    return b"".join([MAGIC, _LEN.pack(len(json_bytes)), json_bytes, *blob_parts])


def unpack_payload(payload: bytes) -> tuple[dict, list[dict], list[tuple[FileEntry, bytes]]]:
    if payload[:8] != MAGIC:
        from ..exceptions import ContainerError

        raise ContainerError("Payload magic mismatch (decryption produced garbage).")
    json_len = _LEN.unpack(payload[8:12])[0]
    json_bytes = payload[12 : 12 + json_len]
    document = json.loads(json_bytes.decode("utf-8"))
    blob = payload[12 + json_len :]

    files: list[tuple[FileEntry, bytes]] = []
    for raw in document.get("files", []):
        entry = FileEntry.from_dict(raw)
        data = blob[entry.offset : entry.offset + entry.length]
        files.append((entry, data))
    return document, document.get("records", []), files
