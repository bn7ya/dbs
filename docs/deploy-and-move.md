# Deploying and moving

The DBS manager can deploy an application in place, move it onto another application, or move
every application on a server onto another server. Each one has a **rehearsal** that changes
nothing and takes a backup before it changes anything for real. A real run asks for your
password and a name typed out.

## Deploying in place

An application keeps up to twelve **deploy steps**, chosen from a fixed list. Each step is one
fixed command whose names are checked, with its own time limit of 1 to 120 minutes (10 by
default). No command line is ever taken from a request.

| Step | Options | Runs |
|---|---|---|
| `git_pull` | `remote` and `branch`, both or neither (letters, digits, `.`, `_`, `/`, `-`) | `git -C PROJECT pull --ff-only --no-rebase [REMOTE BRANCH]`, with `GIT_TERMINAL_PROMPT=0` |
| `compose_pull` | `services` | `ENGINE compose … pull [SERVICE…]` |
| `compose_build` | `services`, `pull` | `ENGINE compose … build [--pull] [SERVICE…]` |
| `compose_up` | `services` | `ENGINE compose … up -d [SERVICE…]` |
| `restart` | — | `ENGINE compose … restart SERVICE`, or `ENGINE restart CONTAINER` |
| `systemd_user_restart` | `unit` (a name ending in `.service`) | `systemctl --user restart UNIT` |
| `pip_install` | `requirements` (a file inside the project folder) | `PYTHON -m pip install -r FILE`, on the server itself |
| `migrate` | — | `manage.py migrate --noinput` |
| `collectstatic` | — | `manage.py collectstatic --noinput` |

`git_pull` and `pip_install` need the application's project folder; the `compose_` steps need
a Compose service, `restart` a container or a Compose service, and `pip_install` an application
on the server itself. Choose the steps on the **Deploy** tab, or from a JSON file:

```bash
echo '[{"kind": "git_pull"}, {"kind": "compose_build", "options": {"pull": true}}, {"kind": "compose_up"}, {"kind": "migrate", "timeout_minutes": 30}]' > steps.json
django_dbs app deploy-steps shop --set steps.json     # asks for your password
django_dbs app deploy shop                            # a rehearsal
django_dbs app deploy shop --real                     # asks for your password and the name
```

**The rehearsal** only reads: `git fetch --dry-run` and `git status --porcelain`,
`compose config --quiet`, `pip --version` and a check that the requirements file is there,
`migrate --plan` and `collectstatic --dry-run`. It takes no backup and changes nothing.

**A real deploy** needs your password and the application's name typed out (`--confirm-name`
from a script). It:

1. checks the application, and records the image its container runs and, when a step pulls
   code, the git `HEAD`;
2. takes a **safety backup**, with no copy left on the server;
3. records the application's `.env` as a version;
4. runs the steps in order, stopping at the first that fails;
5. checks the application again, with `manage.py check` and `manage.py migrate --check`, and
   records the image and the git `HEAD` after.

When a deploy stops after a step that changed something, the deploy page offers **Restore the
safety backup**. It puts the data back as it was before the deploy began; the code and the
images stay as the deploy left them. Rehearse it first; for real it needs your password and the
application's name. From a terminal: `django_dbs redeploy revert JOB_ID [--real]`, with the
deploy's activity number.

## Moving to another application

A move stands the project up as another application, on a new server or in another place on
the same one, that already runs its code with the same environment. The manager carries the
data and the `.env` across, and keeps a way back.

1. **Prepare the new place:** check out the project's code, with its virtualenv or its image,
   django-dbs among its requirements, and the same settings.
2. **Add the new application** with the wizard.
3. On the old application's **Deploy** tab, choose **Move to another application**. Pick the
   new one, the `.env` version to push, whether to replace the new application's data instead
   of merging, and the backup to restore if the old application does not answer (its newest by
   default, or none to stop instead).
4. **Rehearse.** The rehearsal checks the new application, asks the old one whether it answers,
   and restores the backup in a transaction it rolls back. Nothing changes on either side. When
   the new application's database is not migrated yet, it checks the backup in the manager
   instead: that it is whole and opens with the old application's passphrase.
5. **Run it for real** with your password and the new application's name. The manager:
   1. checks the new application;
   2. backs up the old application now, when it answers, with no copy left on the server, or
      uses the backup you chose when it does not;
   3. records the new application's `.env` as a version;
   4. takes a safety backup of the new application's data, when its database is migrated;
   5. pushes the `.env`, runs `migrate`, restores the backup with the old application's
      passphrase, and checks the new application again.

The `.env` goes first on purpose: it carries the old `SECRET_KEY`, which the restored project
needs for its sessions and encrypted fields. Every step is in the audit trail, and a move never
restores a quarantined backup.

When a step after the `.env` push fails, the move stops and names the step. The move page then
offers **Revert the new application**: it pushes the recorded `.env` back and restores the
safety backup over what the move left. Rehearse the revert first; a real one needs your
password and the new application's name.

```bash
django_dbs redeploy start --from old --to new                     # a rehearsal
django_dbs redeploy start --from old --to new --real
django_dbs redeploy revert 412 --real                             # 412: the move's activity number
```

## Moving a server

**Move to another server**, on a server's overview, carries every application on it onto
another server: its code with `.git`, images, volumes, files, `.env` and data. The new server
may have nothing installed; the manager installs what the applications need. The old server
keeps running, untouched, until you point the traffic at the new one.

1. **Choose the new server.** The move offers *Add a new server* and comes back with it
   chosen.
2. **Choose the applications** that move, the folder each takes (the same one by default) and
   its name. Application names are unique in the manager, so a moved application is called
   `NAME (NEW SERVER)` unless you name it.
3. **Plan the move.** The rehearsal only reads, on both servers, and lists what moves: each
   folder and its size, what is left out (the virtualenv when it is made again, a SQLite file),
   git, the images and volumes (the database's own volume stays, because its data is restored
   instead), the database, the Python, the systemd units and nginx sites, and the packages the
   new server lacks.
   - **Blockers** stop the move until you fix them: an unsupported system, a different
     processor for images, no `sudo`, too little space, or a port, folder, file, image, volume,
     unit, site or container already on the new server; a name already taken; an application
     without a stored passphrase.
   - **Notes** say what to check afterwards.
4. **Move for real** with your password, the new server's name typed out, and the `sudo`
   password of the SSH user on the new server when it needs one.

The move then works in phases, each step in the audit trail:

- **Prepare the new server:** check the `sudo` password once; add Docker's own package
  repository when Docker is needed (its signing key is checked against the fingerprint DBS
  ships); install the packages; start the engine and its services; add the users the units run
  as; and check the server again.
- **Each application:**
  - take a fresh backup of it;
  - carry its folder, files kept outside the folder (such as a `.env`), the folders mounted
    into its containers, its images (loaded and their ids compared) and its volumes;
  - write the new folder into a carried `.env` that names the old one;
  - make the backup folder;
  - carry the virtualenv as it is, or make it again from `pip freeze` when the folder, the
    system or the Python differs;
  - create the database for a PostgreSQL or MariaDB on the server itself;
  - start the Compose services that ran (`compose up -d --no-build`, under the same project
    name) or the containers;
  - add the moved application to the manager with the same backup passphrase and answers;
  - run `migrate` and restore the fresh backup into it;
  - install the systemd units and nginx sites with the new folder written into them (a site is
    enabled only when its certificates are there and `nginx -t` passes);
  - check it, and copy its backup plans, paused.

**How things travel.** Everything is read on the old server, written to a private spool on the
manager with its SHA-256, uploaded into a staging folder on the new server
(`~/.dbs-staging/relocation-JOB`), checked there, then put in place. Nothing on the new server
is written over, and no `rm -r` runs: a folder lands beside its place and is renamed into it
only where nothing is.

**Databases.** A database on another machine or a managed service is shared by both servers,
so the move never restores over it. `migrate` and the restore refuse a database that is still
the old application's own (`database_is_the_sources`). Rows written on the old server after its
fresh backup are not carried, so move when it is quiet, or take the old application offline
first.

**When it stops.** A move that stops says which step failed and what it left in the staging
folder, and **Resume the move** starts again from there. Only one move runs on a server at a
time, and a server a move holds cannot be removed.

**`sudo`.** A server move is the one place the manager uses `sudo`. The password is typed for
each move, kept in memory, and reaches the server only on standard input. It is never stored,
logged or audited. The old server only reads; its SSH user needs `sudo` only to read files it
cannot read itself, and the move asks for that password only when you pass
`--source-sudo-password` from a terminal.

**Supported systems.** The new server runs Debian 11, 12 or 13, Ubuntu 22.04, 24.04 or 26.04,
RHEL, Rocky Linux, AlmaLinux or Oracle Linux 8 to 10, CentOS Stream 9 or 10, or Fedora 41 or
later, on amd64 or arm64, with the same container engine as the old one.

From a terminal:

```bash
django_dbs server move web-1 --to web-2                                # a rehearsal
django_dbs server move web-1 --to web-2 --app shop=/srv/shop --name shop=shop-eu
django_dbs server move web-1 --to web-2 --real                         # asks for the passwords
django_dbs server move web-1 --to web-2 --real --resume 512            # 512: the move's activity number
```

- `--app NAME[=FOLDER]` chooses the applications that move, and their folders.
- `--name APP=NEW` names a moved application; `--skip-volume APP:VOLUME` leaves a volume
  behind; `--no-plans` copies no plan.
- `--confirm-name NAME` gives the new server's name from a script.
- `--sudo-password-stdin` reads the `sudo` password after your own; `--no-sudo-password` says
  the SSH user is root or needs none; `--source-sudo-password` also asks for the old server's.

The API is `POST /api/servers/{id}/move/`. Claude can only rehearse a move
(`rehearse_server_move`), and the console runs a real one only with `--no-sudo-password`,
since it never takes a `sudo` password.
