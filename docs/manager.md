# The DBS manager

The DBS manager is a small application that runs on your own machine, or any machine you
choose, and looks after the Django applications on your servers. It connects to them over
SSH and:

- **finds an application from a folder**, whether it runs on the server itself, in a Compose
  service or in a container, under Docker or Podman;
- **pulls its DBS backups**, on demand or on a plan, resumes a transfer that broke, and keeps
  the newest five of each;
- **backs up folders** as encrypted archives and **collects files** the server already makes;
- **browses files** inside the folders you allow, and **keeps every version of a `.env`**,
  encrypted, ready to put one back;
- **restores a backup onto any application**, its own or another;
- **deploys, moves and relocates** applications, after a safety backup (see
  [Deploying and moving](deploy-and-move.md));
- **runs its own commands in a console** and **opens a terminal** on a server or inside a
  container, in the browser;
- **records every action** in its own audit trail, under the account that acted.

Its interface is in English and Arabic, right to left included, and every action is also a
`django_dbs` command.

## Start it

```bash
pipx install django-dbs     # or: pip install django-dbs
django_dbs run              # also: django-dbs run, or dbs run
```

`django_dbs`, `django-dbs` and `dbs` are the same command. If the shell does not find it, pip
put the script in a folder that is not on your `PATH`: run `python -m dbs.manager run`, or
install with pipx. If an installation cannot import one of its packages, `django_dbs` names it
and prints the `pip install --force-reinstall "django-dbs"` line that repairs it.

The first run creates a data folder, a local SQLite database and a sealing key, starts the
manager at `http://127.0.0.1:8765` and opens your browser on a one-time setup page. Choose the
username and password of the **master account**, then set up two-factor sign-in: scan the QR
code with an authenticator app, type the code it shows, and keep the ten recovery codes
somewhere safe. The next `django_dbs run` opens the sign-in page; running it while the manager
is already running only opens the browser on it.

| Option | Meaning |
|---|---|
| `--port PORT` | The port to listen on. Without it, 8765, or a free port when 8765 is taken |
| `--host 127.0.0.1` | The address to listen on. Anything but loopback needs `--trusted-proxy` or `--allow-insecure-http` |
| `--trusted-proxy CIDR` | The address range of the TLS reverse proxy in front of the manager. Repeat for more |
| `--allow-insecure-http` | Listen beyond this computer over plain HTTP, accepting that passwords cross the network unencrypted |
| `--terminal admins\|master\|off` | Who may open a [terminal](#the-terminal): admins (the default), only the master, or no one |
| `--no-browser` | Do not open a browser; the address is printed either way |
| `--data-dir PATH` | Where the manager keeps everything (also `$DBS_MANAGER_HOME`) |
| `--database-url URL` | PostgreSQL or MySQL instead of SQLite (also `$DBS_MANAGER_DATABASE_URL`) |

The data folder holds the database, the backups the manager pulled and its log,
`manager.log`:

| System | Default data folder |
|---|---|
| Linux | `~/.local/share/django-dbs` (or `$XDG_DATA_HOME/django-dbs`) |
| macOS | `~/Library/Application Support/django-dbs` |
| Windows | `%LOCALAPPDATA%\django-dbs` |

`django_dbs paths` prints these, and where the sealing key is. The SQLite database runs in WAL
mode with a 30-second busy timeout and, on Django 5.1 or later, starts every write
transaction at once, so the interface, the scheduler and terminal commands share it without
"database is locked". The manager serves on 16 threads.

## The sealing key

Every server credential, backup passphrase, `.env` version and archive the manager holds is
sealed with AES-256-GCM under one key. The manager keeps that key in the system keychain
wherever one works, and reads it back before relying on it. Where no keychain works, the key
stays in `keys/secret.key` inside the data folder, and the manager warns at start, on the
dashboard and in its health report that anyone who can read the folder can open its secrets.

`DBS_MANAGER_KEY_STORE=keychain` or `=file` chooses the store. The manager never makes a new
key when the keychain does not answer, and refuses to start when the keychain and a key file
disagree, naming both. On Windows, a new data folder is limited to its owner.

## Accounts and roles

Every account has a role, and each role may do everything the one below it may:

| Role | What it may do |
|---|---|
| **viewer** | See the servers, applications, backups, plans, activity, `.env` key names and files; use the console for what a viewer may do |
| **operator** | Check servers and applications; take, verify and download backups; run plans; keep `.env` versions; download files; rehearse restores, moves and deploys |
| **admin** | Add, change and remove servers and applications; read and store backup passphrases; upload and delete backups; change plans; reveal and push `.env` versions; change files; choose deploy steps; restore, move and deploy for real; open a terminal |
| **master** | Everything, and the accounts: add them, set their roles, switch them off and on, reset their two-factor sign-in |

There is exactly one master: the account made at setup. It cannot be demoted or switched off;
it hands the role over instead, with its password and a current code. The interface hides what
a role may not do, and the manager refuses it whichever way it is asked.

Signing in takes the password, then a six-digit code from an authenticator app or one of the
ten single-use recovery codes. An account without two-factor sign-in sets it up at its next
sign-in. A password lasts 30 days; after that, or when the master asks for a new one, the
session can only change it. Repeated failures slow sign-in down for that username, from 2
seconds doubling up to a minute, except from an address the account used in the last 30 days.

The master manages accounts on the **Accounts** page, or from a terminal:

```bash
django_dbs createuser sara --role operator    # a first password; sara picks her own at first sign-in
django_dbs account list                       # role, active, two-factor, password expiry
django_dbs account role sara admin            # giving "master" hands the master role over
django_dbs account disable sara               # and: account enable sara
django_dbs account reset-2fa sara             # two-factor sign-in is set up again at the next sign-in
django_dbs password sara                      # a new password; its 30 days start again
```

The first account is always the master; every later one is `admin`, `operator` or `viewer`.
`--password-stdin` scripts `createuser` and `password`.

## Listening beyond this computer

The manager listens on `127.0.0.1`. To reach it from elsewhere, put a TLS reverse proxy in
front of it and name the proxy's address range:

```bash
DBS_MANAGER_HOST=backups.example.com django_dbs run --host 0.0.0.0 --trusted-proxy 10.0.0.0/24
```

`X-Forwarded-Proto` and `X-Forwarded-For` are believed from that range only, cookies are
`Secure` and HSTS is on. `DBS_MANAGER_HOST` is the name you browse to, and
`DBS_MANAGER_TRUSTED_PROXY` takes the ranges as a comma-separated list. Without
`--trusted-proxy`, a non-loopback `--host` is refused unless you pass
`--allow-insecure-http`; an SSH tunnel to `127.0.0.1` needs neither.

The terminal reads its output with requests that wait up to 15 seconds. Its answers carry
`X-Accel-Buffering: no` and `Cache-Control: no-store`; nginx honours the first unless
`proxy_ignore_headers` lists it, so leave it out, and keep `proxy_read_timeout` above 15
seconds (nginx's default of 60 is enough).

## Servers and applications

A **server** is a machine the manager reaches over SSH: its address and port, the SSH user,
how it signs in (a key the manager made, a key you gave it, or a password, each sealed), the
host key you confirmed, and the container engines it has.

An **application** is one Django project on a server, and where it runs:

| Where it runs | The manager runs `manage.py` … |
|---|---|
| **on the server** (`host`) | with the application's Python, in its project folder |
| **in a Compose service** (`compose`) | through `ENGINE compose [-f FILE]… [-p PROJECT] exec -T SERVICE …`, from the folder that holds the compose file |
| **in a container** (`container`) | through `ENGINE exec [-i] CONTAINER …` |

`ENGINE` is `docker` or `podman`. An application also keeps its paths inside the container and
on the server, its mounts, its backup folder, the folders its Files tab may open, its `.env`
and whether that file is on the server or inside the container, its backup passphrase and its
deploy steps. Backups, plans, `.env` versions, files, deploys and moves belong to an
application, so a server runs as many as it has. The dashboard shows each server with a card
per application.

Two servers that turn out to be one machine (the same address, port, user and host key) can be
joined: the interface offers it, or `django_dbs server merge OLD --into KEEP` moves the
applications across and removes the other, with your password. A server that still runs an
application cannot be removed (`server_has_applications`).

## Add a server

**Add a server** walks you through it:

1. **Address:** the server's name or address, its SSH port and user.
2. **Host key:** the manager shows the fingerprint the server presents and the command to
   compare it on the server. Nothing connects until you confirm it.
3. **Sign-in:** let the manager create a key (it shows the one line to add to the server's
   `~/.ssh/authorized_keys`), or paste a key or a password.
4. **Check:** the manager signs in and asks which container engines answer: Docker and Podman,
   their versions, their Compose, and whether this SSH user may use them.
5. **Add an application**, or come back to it later.

Each server shows a connection dot: online, offline with when it was last seen, or not seen
yet. The manager reaches every server it has not heard from in five minutes, sends a keepalive
every 15 seconds on an open connection, and notices a dropped one. Where the server has the
`timeout` command, every remote command runs under it and stops at its deadline; until a
command whose end was not seen has run out its time, the manager starts no backup, restore or
move on that application (`server_settling`).

## Add an application

You give the manager a server and a folder on it: the Django project's folder, or the folder
holding the compose file that runs it. First the wizard asks **how the project runs**. Every
question may stay on *Not sure*:

| Question | Key | Answers |
|---|---|---|
| Where does Django run? | `runs_in` | `host` (on the server, with a virtualenv), `compose`, `container` |
| Which container engine? | `engine` | `docker`, `podman` |
| Which database? | `database` | `postgresql`, `mysql`, `mariadb`, `sqlite`, `other` |
| Where does the database run? | `database_runs` | `compose` (beside it), `this_server`, `elsewhere` (another machine or a managed service), `file` |
| Where do its settings come from? | `settings_from` | `folder_env` (a `.env` in the folder), `compose_env_file`, `image`, `environment` |
| Where does its code come from? | `source` | `git`, `copied`, `image` |
| What keeps it running? | `process_manager` | `systemd`, `systemd_user`, `supervisor`, `other` (on the server only) |
| Which web server is in front of it? | `web_server` | `nginx`, `other`, `none` (on the server only) |

The answers guide the rest: the folder step says which folder to give, and discovery puts the
place that matches first. Where it finds something else, it says so: *You said PostgreSQL,
but the manager found SQLite.*

Discovery and the check also read what they can without changing anything: the database's
vendor, host and name from the settings (never its password); the git branch, commit, remote
(without credentials) and uncommitted changes; where the `.env` comes from; and the systemd
units, Supervisor files and nginx sites that name the folder. The application's overview has a
**How it runs** card with each answer beside what was found, *Use what was found* and *Edit
how it runs*. Changing the answers needs no password, because they change no command the
manager runs.

When the check finds a problem, it gives the **next step** for that deployment, with the
command to run: add the SSH user to the `docker` group, mount the backup folder into the
service, install django-dbs in the image and rebuild it, create the missing backup folder.

From a terminal, the answers are `--deployment KEY=VALUE` (repeat it) on `app discover`,
`app add` and `app edit`, and `app show` prints them beside what was found.

### What discovery does

1. **The folder.** It lists the folder for `manage.py`, compose files, a `Dockerfile` or
   `Containerfile`, and `.env` files. Left empty, it suggests the project folders it finds in
   the SSH user's home, `/srv`, `/var/www` and `/opt`, two levels down.
2. **Only a folder it can trust.** A folder that another account can write to, or whose parent
   another account can write to, runs nothing: discovery reports it and stops. The same holds
   for a project folder found below it.
3. **Containers.** For each engine the SSH user may use, it lists the containers and inspects
   the first 30, and keeps those that belong to the folder: a Compose project whose working
   folder is in it, or a container with a bind mount from it. Replicas of one Compose service
   are one application, counted. A container whose name or Compose labels could be read as an
   option is left out. The manager keeps 64 KiB of what a command prints, so containers whose
   details pass that together are inspected again in halves; one that passes it alone is left
   out and named in `unread_containers`.
4. **Python and `manage.py`.** In each running container it tries the virtualenvs on the
   container's `PATH`, a `.venv` in its working folder, `/opt/venv`, `/venv`, `/app/.venv`,
   `/usr/local/bin/python3`, `python3` and `python`, and keeps the first that has django-dbs.
   It looks for `manage.py` in the folder's mount, the container's working folder and `/app`,
   `/code`, `/srv`, `/usr/src/app` and `/opt/app`. On the server itself it tries any virtualenv
   in or next to the project, `~/.virtualenvs`, then `python3`.
5. **django-dbs itself.** It runs `manage.py dbs connection --json` where the project runs, for
   the settings module, the backup folder, the file roots, the `.env` path and the django-dbs
   version.
6. **Paths on the server.** A path inside a container is mapped to the server through the
   container's mounts, the longest match first, so the manager knows where the backup folder
   and file roots are on the server. A backup folder on no mount is reported
   (`backup_dir_not_mounted`).
7. **`.env` candidates.** The `.env` django-dbs names, the compose files' `env_file` entries
   and the `.env` beside them, each marked as on the server or inside the container. Their
   contents are not read here.

Each place it found is offered with what it found and its problems (`container_not_running`,
`dbs_missing`, `dbs_too_old`, `backup_dir_not_mounted`), best first. Pick one, check the
settings it filled in (*Show more settings* holds the rest), and the manager checks the
application: its engine answers and its container runs, django-dbs answers, the backup command
works, and the backup folder, the `.env` and the allowed folders are there.

### The backup passphrase and the password

**Store the passphrase** now, read from the application so you never retype it, before the
first backup. **An application's backup passphrase must never change**: the backups taken with
it would no longer open. An application added without it gets a random passphrase of the
manager's own, which the backups the project writes by itself do not use. Then **take a test
backup** and watch it arrive.

Adding an application asks for your password, because the manager will run its Python and
`manage.py` on the server. So does changing what it runs (where it runs, its engine, container
or Compose service, its folders, its Python, its `manage.py` and its settings module), at any
time. The Python must be named `python`, `python3`, `python3.N` or `pypy3`, alone or as an
absolute path, and `manage.py` must be a file called `manage.py`. For an hour after adding a
server, the account that added it searches the server without its password, and changes the
other settings of an application it added until its check passes; after that, those ask for
your password too.

## What a server needs

| On the server | |
|---|---|
| An SSH user that owns the project, with the manager's key in `~/.ssh/authorized_keys` | No `root` and no shell profile. The manager uses `sudo` only to prepare the server a [server move](deploy-and-move.md#moving-a-server) goes to |
| The project, its Python and `manage.py`, on the server or in its image | The manager runs `manage.py dbs …` with fixed arguments |
| `django-dbs` installed and `"dbs"` in `INSTALLED_APPS`, migrated | 0.7.0 or later; 0.8.0 or later to resume a transfer that broke |
| A stable `SECRET_KEY` (or `DBS_PASSPHRASE`) | The backup passphrase comes from it and must never change |
| `DBS_BACKUP_DIR`, writable by the user the project runs as | Where backups wait for the manager; in a container, on a mounted folder |
| For containers: a user that may run `docker`, or rootless `podman` | See [Docker and Podman](#docker-and-podman) |

The project never contacts the manager and keeps nothing about it. A backup the manager asks
for is audited on the server like any other.

## Docker and Podman

For an application in a Compose service or a container, every command goes through the
engine as the SSH user:

```bash
docker compose -f compose.yaml -p shop exec -T -e DJANGO_SETTINGS_MODULE=shop.settings web python manage.py …
podman exec -i shop-web-1 python manage.py …     # -i only when the passphrase goes to stdin
```

- **Running or not.** A Compose service counts as running when the engine lists a running
  container with its project and service labels; a container, when the engine says so.
  `container_not_running` stops a backup before it starts.
- **Backups.** A backup streams out of the container. Its copy waits in the container's
  `DBS_BACKUP_DIR`, where the next run collects it if the stream broke, so keep that folder on
  a mount that outlives the container.
- **Restores.** The backup goes into the container over standard input, into a private file
  under `/tmp` written as the container's own user, is restored there and removed. Nothing is
  staged on the server, and no `cp` or `chown` runs.
- **Leftovers.** Partial backups and restore files older than an hour are swept inside the
  container too.
- **`.env`.** A `.env` on the server is read over SFTP; one inside the container is read and
  replaced in place, and the interface warns that a version pushed there is lost when the
  container is created again.
- **Read-only containers.** `dbs backup --stream` works in a container with a read-only root
  and a `tmpfs` at `/tmp`, as long as `DBS_BACKUP_DIR` is a writable mount.

**Who may use the engine.** For Docker, the SSH user must be in the `docker` group, which
amounts to root on that server, so give it to the user that already deploys the project. With
rootless Podman, run the containers as the SSH user itself; its SSH login needs
`XDG_RUNTIME_DIR` set, as a systemd login does. `podman compose` uses the provider Podman is
set up with, podman-compose included. A bind-mounted folder must belong to the container's user
inside Podman's user namespace: `podman unshare chown 10001:10001 backups` gives it to user
10001 of the container. Backups, restores and the check never use `sudo`.

| Code | Means |
|---|---|
| `container_engine_missing` | Neither Docker nor Podman answers on this server |
| `engine_permission_denied` | The SSH user may not use the engine: add it to the engine's group, or run the containers with rootless Podman as that user |
| `container_not_running` | The application's container, or its Compose service, is not running |

## Off-site copies

The manager pulls; the server never pushes. Every DBS backup run, on demand or from a plan:

1. **collects** the backups waiting in the application's backup folder under its own or its
   plan's name (a stream that broke last time, or copies kept there), skipping any it already
   holds with the same path, size and SHA-256;
2. **streams a fresh backup** to itself with `dbs backup --stream`, showing the bytes as they
   arrive;
3. **verifies** each one: the size and SHA-256 the server reported, then a full decryption;
4. **removes the server's copies** it recorded and verified, keeping the newest `keep_remote`
   of them (0 to 5, none by default). With `keep_remote` at 0, nothing from the run stays on
   the server or in the container once the backup is verified.

The manager keeps at most five good backups per application and plan, and never deletes the
newest one that passed verification. A file that fails verification is quarantined: kept under
a name that is not a backup name, with the reason, never restored and never counted. The five
newest quarantined files stay for you to inspect. A restore or move refuses a quarantined
backup (`backup_quarantined`).

**Transfers that break.** A server with django-dbs 0.8 names the backup it is writing and
reports its progress every 30 seconds. When the connection breaks mid-stream, the manager keeps
what it received, reconnects after 5, 15 and then 45 seconds, waits while the server finishes
the backup, pulls only the rest and checks the SHA-256 of the whole file before it decrypts it.
A file that does not match is pulled again from the start, and quarantined if that copy fails
too. If it cannot reconnect, the run ends as *kept on the server*, not failed, and the next run
collects the backup. A stream stops only when nothing arrives for 15 minutes (30 for a 0.7
server, which reports no progress), and a backup has a day in all.

**Storage.** **Backups** in the menu lists every application's backups in one place, beside
the space they take in the manager, in all and per application. They live in the data folder's
`backups` folder; `django_dbs paths` prints where.

## Plans and their schedule

A plan takes a DBS backup (`dbs`), a folder archive (`archive`) or a file collection
(`collect`) on a schedule: every hour, 3, 6 or 12 hours, every day or every week, or only when
you run it. It keeps 1 to 5 backups in the manager and 0 to 5 on the server.

- **First run.** A plan starts at the moment you choose, and later runs keep its beat.
- **Time zone.** A daily or weekly plan keeps its local time in the time zone you name, such as
  `Europe/Berlin`, across daylight saving changes. UTC is the default.
- **Reschedule.** Move the next run to any moment within a year; later runs follow from it.
- **Pause and resume.** A paused plan does not run. Resumed, it runs at its next beat after
  now; the runs it missed are not made up.

The application's **Schedule** tab does each of these, and so do the API
(`POST /api/backups/plans/ID/reschedule/` with `{"next_run_at": "…"}`, `…/pause/` and
`…/resume/`) and the terminal:

```bash
django_dbs plan add shop nightly --kind dbs --every 1440 --first-run 2026-11-02T03:00+01:00 --time-zone Europe/Berlin --keep 5
django_dbs plan add shop media --kind archive --path /srv/shop/media --every 10080
django_dbs plan add shop dumps --kind collect --path /srv/dumps --pattern "*.sql.gz" --manual
django_dbs plan reschedule PLAN_ID --at 2026-11-03T04:30+01:00
django_dbs plan pause PLAN_ID
django_dbs plan resume PLAN_ID
```

`--every` takes minutes: 60, 180, 360, 720, 1440 or 10080. A plan that keeps fewer backups
than before deletes the oldest on its next run, so that change asks for your password. Two
plans of one application cannot share a name that differs only in case or punctuation.

## Backups, files and `.env`

Each application has tabs:

- **Backups:** take one now, upload one, verify, download, restore.
- **Schedule:** its plans.
- **Files:** browse, upload and download inside the allowed folders.
- **Environment:** every version of the `.env`, compared side by side, its values revealed
  only after you type your password, and pushed back when you need it.
- **Deploy:** deploy in place, or move to another application.
- **Terminal** and **Activity**.

A server has **Overview**, **Applications**, **Terminal** and **Activity**. The **Dashboard**
shows every server with a card per application: its connection, last backup, checks, next plan
and recent failures. **Activity** is the full audit trail, and a running job shows whether its
connection is alive and how much it has moved.

Downloading a folder archive, a collected or an uploaded file decrypts it, and so does
downloading a `.env` from the Files tab, so each asks for your password, and the browser
follows a one-time link that lasts a minute. Deleting a backup or removing an application asks
for it too. The manager reads or replaces no `.env` in a folder, or a folder it links into,
that another account can write to (`env_folder_shared`).

## The same manager from a terminal

Everything the interface does is also a `django_dbs` command. Both call the same code on the
same data folder, so an application added in a terminal appears in the browser, and
**Activity** records both under the account that acted.

```bash
django_dbs server add web-1 --host shop.example.com --user deploy --ssh-password
django_dbs server add web-2 --host 203.0.113.7 --user deploy --key-file ~/.ssh/web-2
django_dbs app discover web-1 --folder /srv/shop     # what is there, best first
django_dbs app add shop --server web-1 --folder /srv/shop --deployment runs_in=compose
django_dbs app add blog --server web-2 --folder /srv/blog --candidate 2 --backup-passphrase
django_dbs backup take --all          # one after another, with a summary; exits 1 if one failed
django_dbs backup list --app shop
django_dbs app remove blog
```

- `server add` shows the host key fingerprint and asks you to confirm it (`--host-key` or
  `--yes` from a script), signs in and checks the server. `--generate-key` prints the line to
  add to `authorized_keys` instead.
- `app add` runs discovery for the folder, adds the place it found first (or the one
  `--candidate N` names from `app discover`), and checks it. Any setting it found can be given
  instead, and `app edit` takes the same.
- A server or an application is named by its name or its id; a backup, plan or `.env` version
  by the id `list` prints. Every command takes `--json`, which prints exactly what the web API
  returns, and a long job prints a progress line every 30 seconds.

Commands act as a manager account: the only one, or the one named with `--as NAME`, within
that account's role. An action the interface protects with your password asks for it here too,
or reads it with `--password-stdin`. Secrets are typed at a prompt or read from standard input,
never passed as arguments. From a script, confirmations take `--yes`; a real restore, deploy,
server move or revert takes `--confirm-name NAME` instead, the name a person would type.
Downloads are saved readable by you alone. While your password has expired, every command says
so on standard error.

A command that takes a backup waits for it and prints the result. It can run while
`django_dbs run` is open: both take the same per-application lock, so a scheduled backup and
one from the terminal never run on one application at once. Starting the manager frees the
locks of jobs whose process is gone.

Every command and option is in the [command reference](reference/commands.md#the-manager-django_dbs).

## The console

**Console** in the menu runs one `django_dbs` command line at a time, as the account you are
signed in with: `app list`, `backup take shop`, `plan pause 3f2c…`. It takes the `server`,
`app`, `backup`, `plan`, `activity`, `env`, `files` and `redeploy` commands, `help` lists them,
and a leading `django_dbs`, `django-dbs` or `dbs` is ignored. A line is at most 2,000
characters, its output at most 256 KiB, and an account runs one line at a time.

The console leaves out what reads this machine's disk or a secret from standard input:
`backup download` and `upload`, `files download` and `upload`, `server add` and `edit`,
`app passphrase`, `env reveal`, `app deploy-steps --set`, `mcp`, and the options `--as` and
`--password-stdin`. A command that needs your password asks for it in the console, and a job
it starts is shown as it runs; the console does not wait for it. Each line is recorded in
**Activity** with its verb and exit code, never its words. Every role may open the console,
and each command is still checked against the role.

`POST /api/console/` with `{"line": "…", "password": "…"}` does the same and answers
`{"exit_code", "output", "activities", "password_required", "error_code"}`.

## The terminal

An admin can open a shell from the browser: on a server, as its SSH user, or for an
application, inside its container with `bash` (or `sh` where there is no `bash`), or in its
project folder on the server. Each one asks for your account password.

- At most four terminals are open at once, two per account.
- A terminal closes after 15 minutes without input, a minute without the browser asking for
  its output, or two hours in all, and when you sign out, your password or your role changes,
  or the manager stops.
- `django_dbs run --terminal master` (or `DBS_MANAGER_TERMINAL=master`) lets only the master
  open one; `--terminal off` switches terminals off.
- Its row in **Activity** records where it opened, its size, how long it ran, the bytes each
  way, how it ended and its exit status, never what was typed or shown.
- It runs as the SSH user, never through `sudo`. The console and the MCP server cannot open
  one.

The API is `/api/terminals/`: `POST` opens one (`mode` `server` or `application`, the id,
`password`, `cols` and `rows`), `GET /api/terminals/ID/output/?cursor=N` waits up to 15
seconds for output, `POST …/input/` sends keystrokes (at most 64 KiB at a time),
`POST …/resize/` changes its size, and `DELETE` closes it.

## Claude at the controls

`django_dbs mcp` is an MCP server, so Claude can add servers and applications, take and verify
backups, set up plans and rehearse restores, deploys and moves, as one account and within its
role. It never sees a secret and cannot do any of those for real. See
[AI assistants](ai-assistants.md#claude-and-the-dbs-manager).

## Moving the manager itself

```bash
django_dbs export manager.dbs                  # database and keys, one encrypted DBS file
django_dbs export manager.dbs --with-backups   # also every backup it pulled
django_dbs import manager.dbs                  # on the new machine, before the first run
```

`export` asks for a passphrase twice; keep it with the file. `import` builds the new
installation beside the data folder and then swaps it in, so an import that stops never leaves
half of one; the next start finishes the swap. It refuses to replace a manager that already
holds servers unless you pass `--replace`, and refuses while a manager runs on that data
folder. The installation it replaces is moved to `DATA-FOLDER.before-import-STAMP`, never
deleted. An export sealed with another key asks once more, or takes `--yes`. With
`DBS_MANAGER_DATABASE_URL`, `import` loads into an empty database instead. An export written by
0.7 imports too: each of its servers becomes a server and an application.
