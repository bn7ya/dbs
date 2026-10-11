# DBS 0.6.0 — release notes

Released 2026-10-11.

```bash
pip install --upgrade django-dbs
python manage.py dbs upgrade
```

Everything the DBS manager does in its interface can now be done from a terminal, or by
Claude, on the same services and the same data. The manager backs up projects that run in
Docker Compose and finds the server's django-dbs wherever it is installed. Restores are more
faithful: permissions and content types land on their own rows, a PostgreSQL backup reads from
one snapshot, and a block damaged in both copies is rebuilt from what each copy still holds.

The full list of changes is in the
[changelog](https://github.com/bn7ya/dbs/blob/main/CHANGELOG.md#060---2026-10-11).

## Highlights

### The manager from a terminal

Every action in the manager's interface is also a `django_dbs` command. Both call the same
services and validate with the same serializers, so a server added in one shows in the other,
and **Activity** records both under the account that acted.

```bash
django_dbs server add shop --host shop.example.com --user deploy --ssh-password
django_dbs backup take --all
django_dbs backup list --server shop
django_dbs plan add shop nightly --kind dbs --every 1440 --keep 14
```

`--json` prints exactly what the web API returns. Actions the interface guards with the account
password ask for it here too, or read it with `--password-stdin`; secrets are prompted for or
read from stdin, never taken as arguments. `django_dbs server import-profiles` brings the
servers of a `dbs-client` config into the manager.

### Claude drives the manager

`django_dbs mcp` is an MCP server over stdio, built in with no new dependency:

```bash
claude mcp add dbs -- django_dbs mcp
```

Its 27 tools cover the overview, servers, backups, plans, activity, `.env` versions by key name,
server files and a rehearsed redeploy. Claude shows you a new server's host key fingerprint
and waits for your yes before adding it. The MCP server never takes the account password,
never returns a secret, and has no tool that restores or redeploys for real, removes, deletes,
pushes a `.env` or re-pins a host key.

### Projects that run in Docker Compose

A server can say its Django runs in a Compose service. The manager then runs every
`manage.py` command inside that service with `docker compose exec -T`, and moves backups in and
out of the container with `docker compose cp`, removing the copies it made.

```bash
django_dbs server add shop --host shop.example.com --user deploy --ssh-password \
  --runtime compose --compose-service backend --compose-file compose.yaml --project-dir /srv/shop
```

Discovery asks Docker which services run beside a Compose file and picks the one whose Python
has django-dbs. The check reports Docker's version and whether the service is running.

### Finding the project on the server

- **Browse the server.** The wizard and the server's settings open the server's folders in a
  dialog, so the project, the backup folder, the allowed folders and the `.env` file are picked
  rather than typed.
- The wizard searches for the project as soon as the server is added and lists every project
  it finds.
- Discovery tries every Python it can find — any virtualenv in or next to the project,
  `~/.virtualenvs`, `python3`, `python` — and keeps the one that imports django-dbs. When the
  saved Python cannot, the check names the error and offers the one that can.
- `python -m dbs.manager` runs the manager when pip installs `django_dbs` into a folder that is
  not on `PATH`.

## Restore fixes

- **Permissions and content types.** They are left out of a backup because `migrate`
  recreates them, but other rows referred to them by id, and a database migrated in another
  order numbers them differently. A relation to a model the backup does not carry is now
  written by natural key and found again by name on restore. A permission the target lacks is
  left out with a warning; a foreign key it cannot find stops the restore and names the row.
  Backups taken before 0.6.0 still restore, with a warning naming the models they refer to
  by id.
- **PostgreSQL backups taken while the project is in use.** Every model is now read from one
  `REPEATABLE READ` snapshot, so a row committed mid-backup can no longer arrive without the row
  it points at.
- **Damage in both copies of one block.** Such a block is now rebuilt codeword by codeword from
  both copies, with the bytes where they differ treated as erasures. The repair summary
  `dbs validate` prints counts the blocks rebuilt this way.

## Upgrading from 0.5.x

`python manage.py dbs upgrade` checks the project and says what, if anything, needs doing.
Coming from 0.4.x or earlier, read the README's
[Upgrading](https://github.com/bn7ya/dbs#upgrading) section too.

- **Nothing to change in your project.** No new migration for the `dbs` app, no new or renamed
  setting, no new dependency, and the container format is unchanged.
- **`dbs schedule` always follows the panel.** Run with no plan flags, it used to follow the
  panel only when the panel's schedule was already on at start. It now always follows the
  panel, unless `DBS_SCHEDULE_INTERVAL` is still set, and while the panel's schedule is off it
  waits and takes no backups. `dbs upgrade` warns about this when `DBS_SCHEDULER = "command"`.
  Turn the schedule on at `/admin/dbs/backupschedule/`, or pass `--interval`.
- **`DBS_BACKUP_DIR` must be writable.** `dbs upgrade` now checks it, and `dbs backup` and
  `dbs schedule` name the path and the reason instead of ending in a traceback.
- **The manager migrates itself.** Its new migrations (`0002_cache_table`,
  `0003_server_runtime`) apply the next time any `django_dbs` command starts. Servers already in
  the manager keep running on the host.

## Deprecated

`dbs-client` prints a deprecation notice on every run and will be removed in a later release.
Move its servers with `django_dbs server import-profiles`, and use `django_dbs backup take` in
place of `dbs-client backup`. The `dbs.client` Python API is unchanged.

## Security

- The manager runs a Python or a `manage.py` it found by itself only when its folder, and the
  folder holding it, are owned by the SSH user or root and nobody else can write to them
  (group write is accepted for the SSH user's own group). A virtualenv planted next to the
  project by another account on a shared server is never run; a project folder you choose
  yourself is always used.
- The version probe no longer imports from the folder it runs in, so a `dbs.py` or `dbs/` in
  the project folder can neither run nor fake the reported version.
- Once a server's setup is over, discovery asks for the account password, as changing the
  server's settings already does.
- Browsing keeps at most 5000 entries of a folder, and one search tries at most 8 Pythons.

## Other changes

- The manager's cache lives in its database, so the per-server backup lock and the sign-in
  throttle hold across processes: a backup from a terminal and one that `django_dbs run`
  schedules never run on one server together.
- A running job holds a database lease while it works, and `django_dbs run` starting up marks
  as interrupted only the jobs whose process is gone, not one a terminal is still running.
- The wizard keeps the setup window open until a check passes, waits for a project search to
  finish before *Next*, and shows only what was found for the folder in the field.
- A check that finds django-dbs missing now says it was not found.

## Licenses

DBS is MIT. The new
[THIRD_PARTY_LICENSES.md](https://github.com/bn7ya/dbs/blob/main/THIRD_PARTY_LICENSES.md) names
the license of every package `pip install django-dbs` brings in, of what the manager's interface
bundles, and of the development tools.

| Installed with django-dbs | License |
|---|---|
| Django, djangorestframework, scikit-learn | BSD-3-Clause |
| cryptography | Apache-2.0 OR BSD-3-Clause |
| argon2-cffi, tomli (Python < 3.11) | MIT |
| reedsolo | Unlicense OR MIT-0 |
| paramiko | LGPL-2.1-or-later |
| waitress | ZPL-2.1 |

The manager's interface bundles Angular and Angular Material (MIT), RxJS (Apache-2.0), tslib
(0BSD), Font Awesome Free (icons under CC BY 4.0, fonts under the SIL OFL 1.1, code under MIT)
and the Tajawal typeface (SIL OFL 1.1). Their full license texts ship inside the wheel in
`dbs/manager/static/dbs_manager/3rdpartylicenses.txt`.

The wheel and the sdist carry `THIRD_PARTY_LICENSES.md` beside `LICENSE`, and the package
metadata declares its license as the SPDX expression `MIT`. Building django-dbs from source
now needs setuptools 77 or later; pip fetches it on its own.
