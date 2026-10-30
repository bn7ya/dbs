# Python API

The public API is what `dbs` and `dbs.transports` export. Everything else is internal and may
change.

## Backups: `dbs`

```python
from dbs import restore_backup, validate_backup, write_backup

summary = write_backup("backup.dbs", "passphrase")    # streams; returns a BackupSummary
print(summary.bytes_written, summary.sha256, summary.records, summary.skipped_files)

report = validate_backup("backup.dbs", "passphrase")  # report.ok, report.summary()
result = restore_backup("backup.dbs", "passphrase")   # result.healed when it repaired damage
```

### `write_backup(output, passphrase, **options) -> BackupSummary`

Streams a backup to a path that does not exist yet, or to any binary file object (an open
file, `sys.stdout.buffer`, a socket's file), with memory that stays flat.

| Option | Default | |
|---|---|---|
| `using` | `"default"` | The database alias to read |
| `models` | every model | The models to back up |
| `registry` | `backup_registry` | The `BackupRegistry` to read model settings from |
| `compress` · `verify` | `True` | Compress the payload; read the backup back and verify it |
| `allow_missing_files` | `False` | Leave out a missing or unreadable file instead of failing |
| `skipped_files` | `None` | A list that receives the files left out |
| `workers` | `1` | Threads for parity and encryption |
| `block_size` · `nsym` · `interleave` | `65536` · `16` · automatic | The block size, parity symbols per codeword, and the distance between a block's two copies |
| `kdf_params` | from settings | The Argon2id cost for this backup |

`BackupSummary` holds `path`, `bytes_written`, `sha256`, `records`, `files`, `skipped_files`,
`models`, `verified`, `compressed`, `payload_bytes`, `payload_sha256`, `format_version`,
`blocks`, `block_size`, `nsym`, `interleave`, `correctable_bytes_per_codeword` and
`burst_tolerance_bytes`.

`create_backup(passphrase, **options) -> bytes` returns a whole backup as bytes, for small
projects, or writes it with `output=PATH`; it takes the same options but `workers` and
`interleave`.

### `restore_backup(data, passphrase, **options) -> RestoreResult`

`data` is bytes, a path or a seekable binary file.

| Option | Default | |
|---|---|---|
| `using` | `"default"` | The database alias to restore into |
| `dry_run` | `False` | Rehearse in a transaction that is rolled back; write no files |
| `flush` | `False` | Delete the rows the backup covers first |
| `load_data` · `write_files` | `True` | Load the rows; write the files |
| `registry` | `backup_registry` | The registry that decides file roots |

`RestoreResult` holds `records_loaded`, `files_written`, `records_would_load` and
`files_would_write` (for a dry run), `records_flushed`, `preexisting_models`, `models`,
`files_refused` and `repair_report`, and `healed` says whether damage was repaired.

### `validate_backup(data, passphrase=None) -> ValidationResult`

Checks the structure and every block, and decrypts when a passphrase is given.
`ValidationResult` has `ok`, `decrypted_ok`, `messages`, `stats`, `repair_report` and
`summary()`.

### Choosing what to back up

`backup_registry` is the registry `dbs.py` modules register into, and `BackupRegistry` makes
another. `ModelBackup` configures one model, and `FieldType` (`VALUE`, `FILE`, `FILE_PATH`,
`EXCLUDE`) says how a field is treated. See
[Choosing what to back up](../project.md#choosing-what-to-back-up).

`default_passphrase()` returns the passphrase DBS would use: `DBS_PASSPHRASE`, or the one
derived from `SECRET_KEY`.

## SSH: `dbs.transports`

```python
from dbs.transports import SSHTarget, open_session

target = SSHTarget(
    host="backups.example.com",
    username="deploy",
    key_filename="~/.ssh/id_ed25519",
    host_key="ssh-ed25519 AAAA…",
    remote_dir="/var/backups/myproject",
)
with open_session(target) as session:
    for item in session.details():
        print(item.name, item.size, item.modified)
```

`dbs.transports` comes with `pip install django-dbs`; paramiko is imported only when you use
it.

**`SSHTarget`** fields: `host`, `username`, `port` (22), `key_filename`, `key_passphrase`,
`private_key`, `password`, `known_hosts`, `host_key`, `remote_dir`, `auto_add_host_key`,
`use_agent`, `connect_timeout`, `keepalive_interval` (15 seconds), `io_timeout` and
`command_timeout` (6 hours). `SSHTarget.from_dict()` builds one from a mapping; it reads
`username` and `key_filename`, and refuses the older `user` and `key_file`.

**Host keys** are verified, and unknown hosts are rejected by default: pin the one key you
expect with `host_key`, or point `known_hosts` at a file. `fetch_host_key(host, port=22)`
returns a `HostKey` whose `fingerprint` you compare with the one the server prints
(`ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`) before you store its `line`. A server that
presents a different key raises `HostKeyError`.

**Functions:** `open_session(target)` returns an `SSHSession` for several operations over one
connection. The single-shot helpers each open their own: `push_backup`, `pull_backup`,
`pull_backup_to`, `list_backups`, `list_backup_details` (a list of `RemoteBackup`: `name`,
`size`, `modified`), `delete_backup` and `check_connection`.

**`SSHSession`** sends a keepalive every 15 seconds and notices a dropped connection. `run()`
returns a `RemoteResult` (`exit_status`, `stdout`, `stderr`, `ok`) and stops a command after
`command_timeout`. `stream()` takes an `idle_timeout`, after which a command with no output on
either stream is stopped, and an `on_stderr_line` callback that sees each line of standard
error as it arrives. It also has `details()`, `names()`, `push()`, `pull()`, `pull_to()`,
`delete()` and `ensure_dir()`.
