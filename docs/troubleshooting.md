# Troubleshooting

## In a project

**Scheduled backups never run.** Open **Health**. "The scheduler has not checked in" means no
worker has served a request since it started, or the server runs uWSGI without
`--enable-threads`; set `DBS_SCHEDULER = "command"` and run `manage.py dbs schedule`.

**"Set DBS_BACKUP_DIR".** The schedule, *Take a backup*, restoring a stored backup,
`dbs backup --stream` and health need it.

**"Cannot keep backups in …".** The user DBS runs as cannot create or write that folder. Point
`DBS_BACKUP_DIR` at one it can. In a container that runs as a non-root user, create the folder
in the image and give it to that user; otherwise a new volume mounted there belongs to root.

**A backup fails with `disk_full`, `permission_denied` or `read_only`.** The backup folder is
full, not writable by the user the project runs as, or on a read-only disk. Older backups are
untouched; free space or fix the folder, and the next backup succeeds. `database_failed` means
the database connection broke while the backup read it.

**A panel job fails with `time_limit`, `memory_limit` or `killed`.** It ran longer than
`DBS_JOB_TIME_LIMIT`, used more than `DBS_JOB_MEMORY_LIMIT`, or its process ended some other
way, as when the server ran out of memory. Raise the limit, or read the server's own log for
the process.

**Panel backups do not start: the process cannot load the project.** The interpreter DBS chose
for panel jobs is not the project's. `manage.py dbs upgrade` names it; set `DBS_JOB_PYTHON` to
the virtualenv's Python, `DBS_JOB_BOOTSTRAP` if the project sets Django up its own way, or
`DBS_JOB_PROCESS = False`.

**`dbs backup` says the file already exists.** It never replaces a backup. Choose a new name
each run, or let the schedule name them.

**A backup stops, naming files it cannot read.** Restore the files, or pass
`--allow-missing-files` to back up without them.

**The panel signed me out.** `python manage.py dbs security unlock USERNAME`, then add your
network to the trusted list. See [the session guard](session-guard.md).

**`/admin/dbs/` gives a 404.** The panel is for superusers only, and needs
`django.contrib.admin` in `INSTALLED_APPS` beside `dbs`.

**A restore raises `RestoreError` about a path.** Add the folder to `DBS_RESTORE_ROOTS`, or map
the old root to a new one with `DBS_RESTORE_PATH_MAP`. `--dry-run` lists every file a restore
would refuse.

**The project will not start after upgrading: `dbs.contrib` is gone.** Delete
`include("dbs.contrib.urls")` from your URLconf and `"dbs.contrib"` from `INSTALLED_APPS`.
Take and restore backups at `/admin/dbs/` or from the DBS manager. `manage.py dbs upgrade`
names the URLconf, but it cannot run while `INSTALLED_APPS` still lists `dbs.contrib`, so remove
that line first.

## The DBS manager

**`django_dbs` is not recognized, or "command not found".** pip installed the script into a
folder that is not on your `PATH`, common with Windows user installs and `pip install --user`;
pip prints that folder in a warning during the install. Add it to `PATH`, or run
`python -m dbs.manager run`.

**`django_dbs` says the installation cannot import a package.** Repair it with
`pip install --force-reinstall "django-dbs"`.

**`django_dbs run` shows "The manager's interface is not built".** You installed from a source
checkout. Install from PyPI, or build it once with `scripts/build_manager_ui.sh`.

**`django_dbs run` will not start: the system keychain refused.** Unlock the keychain and
start again, or set `DBS_MANAGER_KEY_STORE=file` to keep the sealing key in the data folder.

**The manager cannot reach a server.** Check it again on its page, or run
`django_dbs server check SERVER`: it says whether the SSH sign-in or the host key is the
problem, and which container engines answer. `django_dbs app check APP` says whether the
project path, the Python, the container or the application's django-dbs is. An application
whose django-dbs is older than 0.7 answers `dbs_too_old`; upgrade it.

**The check says `engine_permission_denied`.** The SSH user may not use Docker or Podman. Add
it to the `docker` group, or run the application's containers with rootless Podman as that
user. The check never uses `sudo`. `container_engine_missing` means neither engine answers,
and `container_not_running` that the application's container is stopped.

**Discovery found nothing, or ran nothing in the folder.** A folder that another account can
write to, or whose parent another account can write to, is reported and left alone; let only
its owner write there and search again. A container belongs to a folder only through its
Compose working folder or a bind mount from the folder.

**The manager says django-dbs is "Not found" on a server that has it.** The manager runs the
Python saved for that application over a non-interactive SSH sign-in, which loads no
virtualenv. The check names the Python it used and the error it got, and offers the Python
where django-dbs is installed: choose *Use this Python*, or search the folder again from the
application's settings.

**The `.env` tab refuses with `env_folder_shared`.** Another account can write to the folder
the `.env` is in, or the folder it links into, so the manager neither reads nor replaces it.
Let only the project's owner write there.

**Backups taken by the manager fail verification.** They are quarantined, never restored. The
usual cause is a backup passphrase in the manager that is not the application's: it must be
the one its backups were taken with.

**A terminal command says "pick the account to act as".** The manager has more than one
account; add `--as NAME`.

**A command or a page says it needs another role.** Your account's role does not allow it. Ask
the master account for a higher one.

**A command says it needs a secret typed, or a confirmation.** It ran without a terminal, as
from cron. Pass your password on standard input with `--password-stdin` (and the SSH password
with `--ssh-password-stdin`). Confirm with `--yes`, or, for a real restore, deploy, server move
or revert, with `--confirm-name NAME`; the message names the one the command takes.

**The terminal tab is missing or refuses to open.** It is for admins, and asks for your
password every time; `django_dbs run --terminal master` limits it to the master and
`--terminal off` switches it off. `too_many_terminals` means four are open, or two of yours.

**A server move refuses with `database_is_the_sources`.** The moved application's settings
still name the old application's database. A carried `.env` gets the new folder written into
it; check the settings that name the database, then resume the move.
