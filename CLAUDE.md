# DBS — project memory

DBS (PyPI: `django-dbs`) is a Django backup library. It reads a project's models,
relations and files and writes one encrypted, redundant, self-healing file: every
backup stores two copies plus Reed-Solomon parity, so silent corruption is detected
and repaired on restore. Created by Sudum Technology — Research and Development sector.
This project is under active development; treat it as our very tiny contribution to
this world.

## Coding criteria

Follow these for every change:

- Write clean, maintainable, readable code. Let names carry the meaning.
- No comments. The only exception is a concise docstring on a developer-facing public
  API callable or class (the surface listed below).
- Always say "developer", never "end user".
- Never compare DBS to any other tool or solution — no benchmarks, no "unlike X", no
  feature tables ranking us against alternatives. Describe what DBS does on its own terms.

## Public API (the only place docstrings belong)

Re-exported from `dbs/__init__.py`:
`backup_registry`, `BackupRegistry`, `FieldType`, `ModelBackup`,
`create_backup`, `restore_backup`, `validate_backup`.

Re-exported from `dbs/transports/__init__.py`:
`SSHTarget`, `push_backup`, `pull_backup`, `list_backups`.

Everything else (internal functions, classes, modules) carries no docstring and no
inline comments.

## Layout

- `dbs/engine/` — backup, restore, validate, payload assembly.
- `dbs/container/` — on-disk container format and blocks.
- `dbs/crypto/` — Argon2id KDF and AES-256-GCM envelope.
- `dbs/transports/` — optional SSH/SFTP transport.
- `dbs/management/commands/` — `dbs_backup`, `dbs_restore`, `dbs_validate`.
- `dbs/contrib/` — admin UI download/upload.
- `tests/` — pytest suite (pytest-django).

## Test

```bash
pip install -e ".[dev]"
pytest
```
