# Restoring and passphrases

## Restoring

```bash
python manage.py dbs restore backup.dbs --dry-run   # rehearse; change nothing
python manage.py dbs restore backup.dbs             # merge into what is there
python manage.py dbs restore backup.dbs --flush     # replace instead of merge
```

The panel's **Restore** page and the DBS manager's restore do the same, starting with a dry
run.

- **It merges by default.** Rows created after the backup was taken are kept, and an existing
  row takes only the fields the backup carries, so a field the backup leaves out keeps its
  value.
- **`--flush` replaces.** It deletes only the rows the backup covers (the rows a
  `ModelBackup.get_queryset` selects, on the database you restore into), children before
  parents, in the same transaction as the load.
- **The load is one transaction.** Rows load in the order the backup recorded them, parents
  first. If anything fails midway, the database is untouched.
- **Files land with the rows.** Every file's target is checked before any row loads. Files are
  written beside their targets, moved into place when the rows commit, and removed again if
  the load fails.
- **File writes are confined** to `DBS_RESTORE_ROOTS` (or `DBS_FILE_ROOTS` when unset), a
  `ModelBackup`'s own `file_roots`, and the storage of each file field, where a file lands
  under its storage name. Restoring onto a server whose paths differ? Map the old roots to the
  new ones with `DBS_RESTORE_PATH_MAP = {"/srv/old": "/srv/new"}`; each new root must be
  inside a restore root.
- **The dry run checks the same.** `--dry-run` loads everything inside a transaction it rolls
  back, writes no files and never touches a sequence. It names every file a restore would
  refuse, and exits non-zero when there is one.
- **Migration drift is reported**, naming the apps that moved on since the backup.
- **Sequences are raised**, so the next row your project creates does not collide; on
  PostgreSQL never below their current value.
- **Rows the backup leaves out are found again by name.** `migrate` recreates content types
  and permissions on every server, numbered in the order that server migrated, so a backup
  refers to them, and to any other model it does not carry that has a natural key, by that
  key: a group's permissions as `["change_order", "store", "order"]`, a generic relation's
  content type as `["store", "order"]`. A permission the target no longer has is left out with
  a warning; a foreign key it cannot find stops the restore and names the row.

`--no-data` restores only the files, `--no-files` only the rows, and `--database ALIAS`
restores into another database.

### Signals during a restore

Rows are saved the way `loaddata` saves them, with `raw=True`. A `post_save` receiver with side
effects should return early on raw saves:

```python
@receiver(post_save, sender=Order)
def on_order_saved(sender, instance, created, **kwargs):
    if kwargs.get("raw"):
        return
    ...
```

### When the file is damaged

DBS repairs what it can while it reads: a block is taken from whichever of its two copies
verifies, and sparse damage is corrected with Reed-Solomon parity, even in both copies.
`result.healed` (in the [Python API](reference/python-api.md)) and a `WARNING` on the `dbs`
logger say when it did. If a block cannot be recovered from either copy, DBS refuses to restore
and names the blocks. [How it works](how-it-works.md#how-it-heals) has the details.

## Passphrases

Every backup is encrypted under a passphrase. DBS derives it from `SECRET_KEY`, domain
separated so it is never the same bytes Django uses for sessions and tokens. The first of these
wins:

1. `--passphrase` or `--passphrase-stdin` on the command line;
2. the `DBS_PASSPHRASE` environment variable;
3. the `DBS_PASSPHRASE` setting;
4. derived from `SECRET_KEY`.

`python manage.py dbs key` says where the passphrase comes from, and `--show` prints it. Keep
what it prints somewhere safe.

> **Never change a project's backup passphrase.** Every backup is encrypted under the
> passphrase in force when it was written. Change `SECRET_KEY` without keeping the old one, set
> a new `DBS_PASSPHRASE`, or store a different passphrase for the application in the DBS
> manager, and every older backup stops opening. Nobody can open a backup whose passphrase is
> lost.

**Rotating `SECRET_KEY`:** keep the old value in `SECRET_KEY_FALLBACKS`. DBS tries every
fallback when restoring, so a rotation done Django's way does not strand old backups. Keep the
output of `python manage.py dbs key --show` before you rotate.

**In the DBS manager:** the manager stores each application's backup passphrase, sealed, and
hands it to the project on standard input for every backup and restore. Store it once, while
you add the application and before its first backup (*Backup passphrase* in the wizard, or
`django_dbs app capture-passphrase APP`), and never replace it afterwards.
