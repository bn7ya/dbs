# DBS transports

```python
from dbs.transports import (
    SSHTarget, SSHSession, open_session,
    push_backup, pull_backup, pull_backup_to,
    list_backups, list_backup_details, delete_backup, check_connection,
)
```

`SSHTarget` fields: `host`, `username`, `port`, `key_filename`, `key_passphrase`,
`password`, `known_hosts`, `remote_dir`, `auto_add_host_key`, `use_agent`,
`connect_timeout`. Build one from settings with `SSHTarget.from_settings("name")`, or from
an admin-managed row with `BackupTarget.ssh_target()`.

Host keys are rejected unless known. `auto_add_host_key=True` accepts an unknown key on
first contact and gives up detection of a machine-in-the-middle on that connection; prefer
a `known_hosts` path.

Secrets are read from the environment when a `*_env` key names a variable, so a config file
need not hold them: `password_env`, `key_passphrase_env`.

Requires `pip install "django-dbs[ssh]"`.
