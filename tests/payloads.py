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


def header_of(data, passphrase: str) -> dict:
    with opened(data) as handle, open_stream(handle, passphrase) as (_reader, payload):
        header = dict(payload.read_header())
        payload.read_manifest()
        for stream in payload.files():
            stream.drain()
        for _batch in payload.record_batches(parse=False):
            pass
        payload.read_trailer()
        payload.finish()
    return header


def container_of(header: dict, passphrase: str) -> bytes:
    import io

    from dbs.container import DEFAULT_BLOCK_SIZE, DEFAULT_NSYM
    from dbs.engine import frames
    from dbs.engine.backup import _writer_options
    from dbs.engine.pipeline import encoding
    from tests.conftest import FAST_KDF

    stats = {"models": [], "records": 0, "files": 0, "skipped_files": []}
    output = io.BytesIO()
    options = _writer_options(DEFAULT_BLOCK_SIZE, DEFAULT_NSYM, None, FAST_KDF, None)
    with encoding(output, passphrase, compress=True, **options) as stream:
        stream.write(frames.PAYLOAD_MAGIC)
        stream.write(frames.json_frame(frames.HEADER, {"version": frames.PAYLOAD_VERSION, **header}))
        stream.write(frames.json_frame(frames.TRAILER, {"stats": stats}))
    return output.getvalue()
