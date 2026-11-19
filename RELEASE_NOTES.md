# DBS 0.9.0 — release notes

```bash
pip install --upgrade django-dbs   # in a project
python manage.py dbs upgrade

pipx upgrade django-dbs            # on the machine the DBS manager runs on
```

A migration that looked right can turn out to be wrong days later. 0.9.0 keeps the database as
it was on both sides of every migration and every restore, and puts it back when you ask:
tables, rows and migration records.

```text
$ python manage.py migrate
Checkpoint before this migration: /var/backups/shop/shop-before-migrate-20261115-101500Z.dbs
Operations to perform:
  Apply all migrations: ledger
Running migrations:
  Applying ledger.0004_split_customer_name... OK
Checkpoint after this migration: /var/backups/shop/shop-after-migrate-20261115-101502Z.dbs

$ python manage.py dbs restore /var/backups/shop/shop-before-migrate-20261115-101500Z.dbs --flush
Checkpoint before this restore: /var/backups/shop/shop-before-restore-20261118-090000Z.dbs
Checkpoint after this restore: /var/backups/shop/shop-after-restore-20261118-090003Z.dbs
9 tables were rebuilt as the checkpoint's migrations describe them.
No longer applied (1): ledger.0004_split_customer_name
Restored 1204 records and 0 files.
```

**Nothing you use is removed or renamed, and one thing behaves differently on purpose.** Where
`DBS_BACKUP_DIR` is set, `python manage.py migrate` with something to apply, and
`python manage.py dbs restore`, now write two backups of the database into that folder, and do
not start when the first cannot be written. On a large database that takes time: give a deploy
step that migrates the room for it. `DBS_MIGRATION_CHECKPOINTS = False` switches it off for a
project, `--no-checkpoint` skips it once, and a project with no `DBS_BACKUP_DIR` migrates as
before. Every command, option, setting, REST route and MCP tool of 0.8 works as it did, and
your backups restore with the same passphrase.
[Stability](https://github.com/bn7ya/dbs/blob/main/docs/stability.md) says what is covered.

The full list is in the
[changelog](https://github.com/bn7ya/dbs/blob/main/CHANGELOG.md#090---2026-11-19). Coming from
0.7.x, read the [0.8.0 release notes](https://github.com/bn7ya/dbs/blob/v0.8.0/RELEASE_NOTES.md)
first.

## Checkpoints around migrations and restores

- **`migrate`** writes a checkpoint before the first migration it applies and another after the
  last. If the first cannot be written and verified, the migration does not start. When a
  migration fails, the message names the checkpoint and the command that puts it back.
- **`dbs restore`**, the panel's restore and the manager's restore write the same pair around a
  restore, so a restore can be undone too.
- **`makemigrations`** first checks that the next migration can have its checkpoint: the
  backup folder can be written, a passphrase is there and the folder has room. It writes no
  migration otherwise.
- **`python manage.py dbs checkpoints`** lists them, with the migrations each stands beside.

A checkpoint is an ordinary encrypted backup, verified after it is written. It holds every
table Django's migrations manage, read through the models as the applied migrations describe
them, and the list of applied migrations. It holds no files, and none of DBS's own tables: the
audit trail is never rolled back.

Checkpoints are counted apart from your scheduled and manual backups, and neither removes the
other. The newest *before* and the newest *after* are always kept; older ones go, oldest first,
once there are more than `DBS_MAX_BACKUPS`.

## Going back to before a migration

```bash
python manage.py dbs checkpoints                       # find the one before the migration
python manage.py dbs restore PATH --flush --dry-run    # what would change; changes nothing
python manage.py dbs restore PATH --flush              # put it back
```

The restore drops the tables the checkpoint carries, creates them again as its migrations
describe them, loads its rows and sets `django_migrations` back, whether one migration ran
since or five. It never runs a migration backwards, so a migration that cannot be reversed is
no obstacle. It checks everything before it changes anything, and on PostgreSQL and SQLite it
is one transaction. MySQL and MariaDB cannot roll a table change back, so there the checkpoint
written just before the restore is the way back.

Two things to know: a trigger, a view or an index that a migration created with raw SQL is not
rebuilt, and the restore names those migrations; and the faulty migration is still in your
code afterwards, so fix or remove it before the next `migrate`.
[Checkpoints](https://github.com/bn7ya/dbs/blob/main/docs/restoring.md#checkpoints) in the
restoring guide has every detail.

## A backup belongs to its application

Two projects that share a `SECRET_KEY` derive the same passphrase, so each could restore the
other's backups into its own database. Every backup written by 0.9.0 records the application
it belongs to, and a restore, a dry run included, refuses one that belongs to another:

```text
Restore failed: This backup belongs to the application 'shop', and this project is 'depot'.
```

The name is the project's package, the first part of `ROOT_URLCONF`, unless `DBS_APPLICATION`
sets it. The same project on another server or in another folder is the same application, so
moving it and restoring it elsewhere need nothing. `--another-application` restores a backup
that really is meant for this project. A backup written before 0.9.0 records no application
and restores as it did. `python manage.py dbs upgrade` says when the package has a name other
projects share, such as `config`, and prints the line to add.

## More than five backups

- **`DBS_MAX_BACKUPS`** sets the most backups a project's backup folder keeps: 5 unless set,
  from 1 to 10,000. The panel's schedule, `dbs schedule --keep` and `dbs backup --stream`
  keep up to it.
- **`DBS_MANAGER_MAX_BACKUPS`**, in the manager's environment, is the most it keeps of a plan
  and of an application's one-off backups: 5 unless set, from 1 to 10,000. A plan leaves up to
  the application's own `DBS_MAX_BACKUPS` on its server. The plan form shows both limits.

## Updating DBS from the manager

- **In an application.** *Update django-dbs* on an application's **Deploy** page, or
  `django_dbs app update-dbs APP`, installs a release where the application runs: the
  manager's own unless `--to X.Y.Z` names one. It rehearses first. For real it checks the
  application, takes a safety backup, installs the release, runs `manage.py dbs upgrade`, runs
  the application's restart steps and checks again. An application in a container is refused:
  put the release in its image.
- **The manager itself.** *Update DBS* on the **About** page installs a newer release for the
  master and restarts the manager on the same address. In a terminal, `django_dbs update` does
  the same with the manager stopped; `django_dbs update --check` only looks.

## Every statement in a transaction

Every statement DBS sends to a database, in a project and in the manager, now runs inside a
transaction, and what belongs together is one transaction: a job with its audit row and its
lease, a password with its audit row, a lockout with the anomaly behind it. A transaction is
never left open while the manager waits for a server. Nothing changes in what you call or
configure.

- **SQLite keeps writing during a backup.** With `"transaction_mode": "IMMEDIATE"`, the setting
  `manage.py dbs upgrade` recommends, a backup used to hold the database's write lock for as
  long as it read. A backup, a checkpoint and everything else that only reads now begin
  without that lock, and still read from one snapshot.
- **A checkpoint is one snapshot.** The migrations it records and the rows it carries are read
  together.

## Smaller things

- `django_dbs server add` says its SSH port is 22 unless `--port` names another; the menu's
  form shows it.
- `dbs validate FILE --passphrase` names the application a backup records and, for a
  checkpoint, which migrations it stands beside.
- The tests that need a real SSH server now run against virtual machines, and a server move is
  tested from one machine to a second, bare one.

## Upgrading

In a project:

```bash
pip install --upgrade django-dbs
python manage.py dbs upgrade
```

`dbs upgrade` applies one small migration and reports three new steps: *migration
checkpoints*, *application name* and *maximum backups*. Backups keep their format, so 0.8 and
0.9 read each other's.

On the manager's machine, `pipx upgrade django-dbs`; it migrates itself the next time any
`django_dbs` command starts, and keeps backing up servers on 0.8. From 0.9.0 on, the manager
can do this step for you.
[Upgrading](https://github.com/bn7ya/dbs/blob/main/docs/upgrading.md#from-08x) has the rest.
