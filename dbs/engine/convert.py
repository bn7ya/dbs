from __future__ import annotations

import hashlib
import io

from ..container.stream import layout_problem
from ..crypto.kdf import KDFParams
from ..exceptions import ContainerError, CorruptionError, CryptoError
from ..keys import with_passphrase
from ..serialize import RECORD_BATCH_ROWS
from . import frames
from .backup import _fitting_interleave, _kdf_params_from_settings
from .pipeline import encoding
from .restore import _read_v1_payload, ordered_records


def convert_v1(data: bytes, passphrase: str | None) -> bytes:
    return with_passphrase(lambda secret: _converted(data, secret), passphrase)


def _converted(data: bytes, passphrase: str) -> bytes:
    from .validate import validate_backup

    result = _read_v1_payload(data, passphrase)
    buffer = io.BytesIO()
    with encoding(
        buffer,
        passphrase,
        compress=result.manifest.get("compression") == "zlib",
        **_writer_options(result.manifest),
    ) as stream:
        _emit(stream.write, result.document, result.records, result.files)
    converted = buffer.getvalue()
    check = validate_backup(converted, passphrase)
    if not check.ok:
        raise ContainerError(f"The converted backup did not validate: {check.summary()}")
    return converted


def _writer_options(manifest: dict) -> dict:
    blocks = manifest.get("blocks") or {}
    block_size = blocks.get("block_size")
    nsym = blocks.get("nsym")
    interleave = _fitting_interleave(block_size, nsym)
    if layout_problem(block_size, nsym, interleave):
        block_size, nsym = None, None
    options = {"kdf_params": _kdf_params(manifest.get("crypto") or {})}
    if block_size is not None:
        options.update(block_size=block_size, nsym=nsym, interleave=interleave)
    return options


def _kdf_params(material: dict) -> KDFParams:
    candidates = []
    try:
        candidates.append(KDFParams.from_dict(material.get("params") or {}))
    except (CryptoError, KeyError, TypeError, ValueError, AttributeError):
        pass
    candidates.extend([_kdf_params_from_settings(), KDFParams()])
    for params in candidates:
        try:
            params.validate_untrusted()
        except CryptoError:
            continue
        return params
    return KDFParams()


def _order(document: dict, records: list) -> list:
    order = [label for label in document.get("order") or [] if isinstance(label, str)]
    known = set(order)
    for record in records:
        label = record.get("model")
        if isinstance(label, str) and label not in known:
            order.append(label)
            known.add(label)
    return order


def _emit(emit, document: dict, records: list, files: list) -> None:
    ordered = ordered_records(document, records)
    order = _order(document, ordered)
    emit(frames.PAYLOAD_MAGIC)
    emit(
        frames.json_frame(
            frames.HEADER,
            {
                "version": frames.PAYLOAD_VERSION,
                "created": document.get("created"),
                "django_version": document.get("django_version"),
                "migrations": document.get("migrations"),
                "order": order,
            },
        )
    )
    for start in range(0, len(files), frames.MANIFEST_BATCH):
        batch = files[start : start + frames.MANIFEST_BATCH]
        emit(frames.json_frame(frames.MANIFEST, [frames.manifest_item(entry) for entry, _data in batch]))
    for index, (entry, data) in enumerate(files):
        digest = hashlib.sha256(data).hexdigest()
        if digest != entry.sha256:
            raise CorruptionError(f"File {entry.name!r} failed its integrity hash after extraction.")
        for start in range(0, len(data), frames.FILE_CHUNK_BYTES):
            emit(frames.file_data_frame(index, data[start : start + frames.FILE_CHUNK_BYTES]))
        emit(frames.file_end_frame(index, size=len(data), sha256=digest))
    counts = {label: 0 for label in order}
    batch: list = []
    for record in ordered:
        if batch and (batch[-1]["model"] != record["model"] or len(batch) >= RECORD_BATCH_ROWS):
            _emit_records(emit, batch)
            batch = []
        batch.append(record)
        counts[record["model"]] += 1
    if batch:
        _emit_records(emit, batch)
    stats = document.get("stats") or {}
    skipped = [item for item in stats.get("skipped_files") or [] if isinstance(item, str)]
    emit(
        frames.json_frame(
            frames.TRAILER,
            {
                "stats": {
                    "models": [{"model": label, "count": counts[label]} for label in order],
                    "records": len(ordered),
                    "files": len(files),
                    "skipped_files": skipped,
                }
            },
        )
    )


def _emit_records(emit, batch: list) -> None:
    body = frames.json_bytes(batch)
    if len(body) <= frames.MAX_FRAME_BYTES:
        emit(frames.frame(frames.RECORDS, body))
        return
    if len(batch) == 1:
        raise ContainerError(
            f"{batch[0].get('model')} {batch[0].get('pk')!r} is larger than one record frame holds."
        )
    middle = len(batch) // 2
    _emit_records(emit, batch[:middle])
    _emit_records(emit, batch[middle:])
