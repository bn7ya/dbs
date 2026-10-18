from __future__ import annotations

from dbs.container import read_format_version
from dbs.container.format import STREAM_FORMAT_VERSION
from dbs.engine.inputs import opened, whole
from dbs.engine.restore import ReadResult, _read_v1_payload, open_stream


def read_payload(data, passphrase: str) -> ReadResult:
    with opened(data) as handle:
        if read_format_version(handle) == STREAM_FORMAT_VERSION:
            return _read_stream_payload(handle, passphrase)
        return _read_v1_payload(whole(handle), passphrase)


def _read_stream_payload(handle, passphrase: str) -> ReadResult:
    records: list = []
    files: list = []
    with open_stream(handle, passphrase) as (reader, payload):
        header = payload.read_header()
        payload.read_manifest()
        for stream in payload.files():
            data = b"".join(stream.chunks())
            if not stream.skipped:
                files.append((stream.entry, data))
        for batch in payload.record_batches():
            records.extend(batch)
        payload.read_trailer()
        payload.finish()
    document = {
        **header,
        "stats": payload.stats,
        "records": records,
        "files": [entry.to_dict() for entry, _data in files],
    }
    manifest = {"format": "DBS", "version": STREAM_FORMAT_VERSION, "flags": reader.flags}
    return ReadResult(manifest, document, records, files, reader.report)
