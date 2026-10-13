# DBS transports

Requires `pip install "django-dbs[ssh]"`.

```python
from dbs.transports import (
    SSHTarget, SSHSession, open_session,
    push_backup, pull_backup, pull_backup_to,
    list_backups, list_backup_details, delete_backup, check_connection,
    fetch_host_key, HostKey, HostKeyError,
)
```

`SSHTarget` fields: `host`, `username`, `port`, `key_filename`, `key_passphrase`,
`private_key`, `password`, `known_hosts`, `host_key`, `remote_dir`, `auto_add_host_key`,
`use_agent`, `connect_timeout`, `keepalive_interval` (15 seconds), `io_timeout` (30
seconds) and `command_timeout` (6 hours). Build one directly, or from a dict with
`SSHTarget.from_dict(...)`, where `password_env` and `key_passphrase_env` name environment
variables that hold the secrets.

Host keys are rejected unless known. `host_key="<type> <base64>"` pins exactly one key and
ignores the system known_hosts. `fetch_host_key(host, port)` returns a `HostKey` with the
`fingerprint` to compare and the `line` to store. A changed or untrusted key raises
`HostKeyError`, a `ConfigurationError`. `auto_add_host_key=True` accepts an unknown key on
first contact and gives up detection of a machine-in-the-middle on that connection; prefer
`host_key` or a `known_hosts` path.

A session sends a keepalive every `keepalive_interval`, bounds SFTP reads by `io_timeout`,
and stops a remote command after `command_timeout`: a dropped connection raises
`ConnectionLost`, an overrun `RemoteTimeout`. `SSHSession.stream()` writes a command's
standard output to a file as it arrives. Uploads and downloads go through a private partial
file: a push never replaces a backup already on the server, and a pull never replaces a local
file.

The panel no longer pushes backups anywhere; the DBS manager pulls them with these
sessions. Use the transports from your own scripts.
