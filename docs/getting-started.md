# Getting started

This guide takes you from nothing to a project whose backups are taken, checked and kept
somewhere other than the server it runs on. It has three parts, and you can stop after any of
them:

1. [Back up a Django project](#1-back-up-a-django-project): a few settings and one command.
2. [Use the panel](#2-use-the-panel): schedule backups and restore them from the Django admin.
3. [Look after your servers with the DBS manager](#3-look-after-your-servers-with-the-dbs-manager):
   a local application that pulls every project's backups to your own machine.

You need Python 3.9 or later and Django 4.2 to 6.x.

## 1. Back up a Django project

### Install

```bash
pip install django-dbs
```

One package brings everything DBS uses: the backup library, the session guard's anomaly
detector, SSH support and the DBS manager. Your project's web process imports only what it
needs, so the manager's packages never load there.

### Add it to your settings

```python
# settings.py
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # your apps…
    "dbs",
]

MIDDLEWARE = [
    # Django's defaults, AuthenticationMiddleware among them…
    "dbs.security.middleware.DBSSecurityMiddleware",
]

DBS_BACKUP_DIR = "/var/backups/myproject"
```

Two things matter from the start:

- **`SECRET_KEY` must be stable.** DBS derives the backup passphrase from it, and a project's
  backup passphrase must never change: backups written with the old one would no longer
  open. If you ever rotate `SECRET_KEY`, keep the old value in `SECRET_KEY_FALLBACKS`.
- **`DBS_BACKUP_DIR`** is where backups are kept, at most five. The user your project runs
  as must be able to write there.

`DBSSecurityMiddleware` goes below `AuthenticationMiddleware`. It guards the panel; see
[the session guard](session-guard.md).

Then:

```bash
python manage.py migrate
python manage.py dbs upgrade     # checks your setup and says exactly what is missing
```

### Take, check and restore a backup

```bash
python manage.py dbs backup backup.dbs                  # write an encrypted backup
python manage.py dbs validate backup.dbs --passphrase   # check every block and decrypt it
python manage.py dbs restore backup.dbs --dry-run       # rehearse a restore; changes nothing
python manage.py dbs restore backup.dbs                 # restore for real
```

There is no passphrase to invent: DBS derives one from `SECRET_KEY`. Run
`python manage.py dbs key --show` once and keep what it prints somewhere safe. Without it,
nobody can open your backups if `SECRET_KEY` is lost.

A backup is one file holding your rows, their relations and your uploaded files. It is
encrypted, and it holds two copies of your data plus Reed-Solomon parity, so damage to the
file is found and repaired when you restore. [How it works](how-it-works.md) explains the
format.

## 2. Use the panel

With `dbs` installed beside `django.contrib.admin` and migrated, sign in to the admin as a
superuser and open **`/admin/dbs/`**. There is no `urls.py` change to make.

On your first visit, a short wizard asks which networks you sign in from and how strict the
session guard should be. Then:

1. **Schedule** → tick *enabled*, choose an interval (`6h`, `1d`) and how many backups to
   keep (1 to 5). Backups now run on their own, inside your web workers.
2. **Health** shows whether the last backup is recent, valid and still on disk.
3. **Backups** lists every backup, with *download* and *restore*. A restore starts as a dry
   run; a real one needs the file's name typed out.

Everything the panel does is written to a tamper-evident **Audit** trail. The panel keeps
backups on this server and pushes nothing anywhere; copies elsewhere are the DBS manager's
job. [The panel guide](panel.md) covers every page.

## 3. Look after your servers with the DBS manager

The DBS manager is an application you run on your own machine. It connects to your servers
over SSH, finds each Django project, pulls its backups to your machine on a schedule,
verifies them, and can restore, deploy or move a project. It needs nothing else on your
machine: no Node, no Docker, no Redis and no database server.

### Start it

```bash
pipx install django-dbs     # or pip install django-dbs
django_dbs run              # also: django-dbs run, or dbs run
```

The first run creates a data folder, starts the manager at `http://127.0.0.1:8765` and
opens your browser on a one-time setup page:

1. Choose the username and password of the **master account**.
2. Scan the QR code with an authenticator app, type the code it shows, and keep the ten
   recovery codes somewhere safe.

The next `django_dbs run` opens the sign-in page.

### Add a server

**Servers → Add a server** walks you through it:

1. **Address:** the server's name or address, its SSH port and user.
2. **Host key:** the manager shows the fingerprint the server presents, with the command to
   compare it on the server. Nothing connects until you confirm it.
3. **Sign-in:** let the manager create a key (it shows the line to add to the server's
   `~/.ssh/authorized_keys`), paste a key, or give a password.
4. **Check:** the manager signs in and reports the system and which container engines answer.

On the server, the project needs `django-dbs` installed and `"dbs"` in `INSTALLED_APPS`,
with `DBS_BACKUP_DIR` set, as in part 1. The SSH user needs no `root`.

### Add an application

An application is one Django project on a server. **Add an application** asks:

1. **How it runs:** on the server with a virtualenv, in a Compose service or in a container;
   Docker or Podman; which database and where; where its settings and code come from. Every
   question may stay on *Not sure*.
2. **Folder:** the project's folder, or the folder holding its compose file.
3. **Discovery:** the manager finds the project there, with its Python, `manage.py`, settings
   and backup folder, and says where something differs from your answers.
4. **Review and check:** confirm what it found; the manager checks the application.
5. **Backup passphrase:** read it from the application once, now. It must never change.
6. **Test backup:** watch the first backup arrive and pass verification.

Then open the application's **Schedule** tab and add a plan: a DBS backup every day, kept
five times on your machine. [The manager guide](manager.md) covers everything else: Docker
and Podman, `.env` versions, files, the console and terminal, accounts and roles, and the
same commands from a terminal.

### Let Claude help

```bash
claude mcp add dbs -- django_dbs mcp
```

Then ask Claude to add your servers, find their applications, take and verify backups or
set up plans. It never sees a secret, and it can only rehearse a restore, a deploy or a move.
See [AI assistants](ai-assistants.md).

## Where to go next

- [DBS in a Django project](project.md): settings, large tables, streaming backups and
  choosing what to back up.
- [Restoring](restoring.md): what a restore does, and passphrases.
- [Deploying and moving](deploy-and-move.md): deploy in place, move to another application,
  move a whole server.
- [Troubleshooting](troubleshooting.md), when something does not work.
