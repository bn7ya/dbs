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
restores into another database. A restore that loads rows writes a
[checkpoint](#checkpoints) of the database before it starts and another when it has finished.

### A backup belongs to its application

Every backup written by 0.9.0 or later records the application it belongs to: the name in
`DBS_APPLICATION`, or the project's package (the first part of `ROOT_URLCONF`) when that is not
set. A restore, a dry run included, refuses a backup that records another name, and one that
records this name but holds none of this project's own models. Two projects that share a
`SECRET_KEY` can each decrypt the other's backups; neither can restore them by accident.

```
Restore failed: This backup belongs to the application 'shop', and this project is 'depot'.
```

The same project on another server, in another folder or on another database is the same
application, so moving it and restoring it elsewhere need nothing. When a backup really is meant
for another application, such as after renaming the project's package, say so:

```bash
python manage.py dbs restore backup.dbs --another-application
```

or set `DBS_APPLICATION` to the name the backups record. Set it before the first backup when the
package has a name other projects share, such as `config`; `manage.py dbs upgrade --check` says
when it does. A backup written before 0.9.0 records no application and restores as it always
did. `manage.py dbs validate FILE --passphrase` names the application a backup records.

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

## Checkpoints

A migration that looked right can turn out to be wrong days later, when its backup is long
gone. So wherever `DBS_BACKUP_DIR` is set, DBS keeps the database as it was on both sides of
every change to its tables:

- **`python manage.py migrate`** with something to apply writes a checkpoint before the first
  migration runs and another after the last one. A checkpoint that cannot be written and
  verified stops the migration before it starts. When a migration fails, the message names the
  checkpoint and the command that puts it back.
- **`python manage.py dbs restore`**, the panel's restore and the DBS manager's restore write
  the same pair around the restore.
- **`python manage.py makemigrations`** first checks that the next migration can have its
  checkpoint: the backup folder can be written, a passphrase is there and the folder has room
  for two more. It writes no migration otherwise, and says what is missing.

```
$ python manage.py migrate
Checkpoint before this migration: /var/backups/shop/shop-before-migrate-20261115-101500Z.dbs
Operations to perform:
  Apply all migrations: ledger
Running migrations:
  Applying ledger.0004_split_customer_name... OK
Checkpoint after this migration: /var/backups/shop/shop-after-migrate-20261115-101502Z.dbs
```

A checkpoint is an ordinary backup file, encrypted under the project's passphrase and verified
after it is written. It holds every table Django's migrations manage on that database, whole,
together with the list of applied migrations, and no files: a migration does not touch them.
It is read through the models as the applied migrations describe them, so it is right even
while the code is already ahead of the database. DBS's own tables, the audit trail among them,
are not in it and are never rolled back.

**What is kept.** Checkpoints are counted apart from scheduled and manual backups, and neither
removes the other. The newest *before* and the newest *after* are never removed; older ones go,
oldest first, once there are more than `DBS_MAX_BACKUPS` (5 unless set, up to 10,000).
`python manage.py dbs checkpoints` lists them with the migrations each one stands beside, and
`--json` prints the same list for a script.

**When none is written.** `migrate` with nothing to apply, `--plan` and `--check`; a database
with no migration applied yet; a test database; a run that applies only DBS's own migrations;
`migrate --no-checkpoint` and `dbs restore --no-checkpoint`; `DBS_MIGRATION_CHECKPOINTS = False`;
and a project with no `DBS_BACKUP_DIR`, which gets one line saying so. A dry run of a restore
and `--no-data` write none either.

Each `migrate` and each restore therefore costs two backups of the database. On a large
database give a deploy step that migrates the time for it, or switch checkpoints off for that
run with `--no-checkpoint`.

### Going back to before a migration

Restoring a checkpoint puts back the tables, the rows and the migration records it was taken
with, however many migrations ran since:

```bash
python manage.py dbs checkpoints                       # find the one before the migration
python manage.py dbs restore PATH --flush --dry-run    # what would change; changes nothing
python manage.py dbs restore PATH --flush              # put it back
python manage.py showmigrations                        # the faulty migration is unapplied again
```

- **It rebuilds, it does not reverse.** DBS never runs a migration backwards, so a migration
  that cannot be reversed, or whose reverse is wrong, is no obstacle. It drops the tables the
  checkpoint carries, creates them again as the checkpoint's migrations describe them, loads
  the rows and rewrites `django_migrations` to what was applied then.
- **It needs `--flush`**, because it replaces tables. `--no-schema` loads the checkpoint's rows
  into the tables as they are now, like any other backup.
- **It checks before it changes anything.** The checkpoint must belong to this application, its
  migrations must still be in the project, and the tables they describe must match the ones it
  was taken from. The dry run reports the tables that would be rebuilt, the migrations that
  would no longer be applied and the ones recorded again, and runs no statement that changes a
  table.
- **On PostgreSQL and SQLite it is one transaction**: a failure leaves the database as it was.
  MySQL and MariaDB cannot roll a table change back, so there the file is checked whole first,
  and the checkpoint written just before the restore is the way back.
- **Raw SQL is not repeated.** A trigger, a view or an index a migration created with `RunSQL`
  is not rebuilt; the dry run and the restore name those migrations.
- **Keep the faulty migration unapplied until it is fixed.** The code still holds it, so the
  next `migrate` would apply it again. Fix or remove it first, then migrate; that `migrate`
  writes its own pair of checkpoints.

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
