# DBS transports

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
`use_agent`, `connect_timeout`. Build one from settings with
`SSHTarget.from_settings("name")`, or from an admin-managed row with
`BackupTarget.ssh_target()`.

Host keys are rejected unless known. `host_key="<type> <base64>"` pins exactly one key and
ignores the system known_hosts. `fetch_host_key(host, port)` returns a `HostKey` with the
`fingerprint` to compare and the `line` to store. A changed or untrusted key raises
`HostKeyError`, a `ConfigurationError`. `auto_add_host_key=True` accepts an unknown key on
first contact and gives up detection of a machine-in-the-middle on that connection; prefer
`host_key` or a `known_hosts` path.

Secrets are read from the environment when a `*_env` key names a variable, so a config file
need not hold them: `password_env`, `key_passphrase_env`.

Requires `pip install "django-dbs[ssh]"`.
