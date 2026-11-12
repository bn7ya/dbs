# DBS 0.8.3 — release notes

```bash
pipx upgrade django-dbs            # on the machine the DBS manager runs on
pip install --upgrade django-dbs   # in a project
```

0.8.3 adds one thing: **the menu**. Type `django_dbs` alone in a terminal, or `django-dbs` or
`dbs`, and the manager opens there, moved through with the arrow keys. Until now the bare
command printed its help, and everything the manager does outside the browser meant typing a
command with its options.

```text
 DBS manager 0.8.3                                                             sara · admin
┌────────────────────┬─────────────────────────────────────────────────────────────────────┐
│▸ Dashboard         │ Dashboard                                                           │
│  Servers           │                                                                     │
│  Applications      │ Servers 2   Applications 2   Stored here 0 B   Failures in 7 days 0 │
│  Backups           │                                                                     │
│  Activity          │  ! Export the manager's data: open Manager, then Export.            │
│  Accounts          │                                                                     │
│  Manager           │   Name    Where          State           Last backup  Next run      │
│  All commands      │ ▸ db-1    10.0.0.9       ○ Not seen yet                             │
│                    │   web-1   10.0.0.5       ○ Not seen yet                             │
│                    │     blog  on the server  ○ Not checked   none yet     no plan       │
│                    │     shop  on the server  ○ Not checked   none yet     no plan       │
│                    │                                                                     │
│                    │                                                                     │
│                    │                                                                     │
│                    │                                                                     │
│                    │                                                                     │
└────────────────────┴─────────────────────────────────────────────────────────────────────┘
 ↑↓ Move   Enter Open   a Add a server   r Refresh   Esc Back   ? Keys
```

Only the machine the manager runs on needs the new version. It has no migration to run and
brings no new package, and a server may stay on 0.8.0, 0.8.1 or 0.8.2. In a project,
`python manage.py dbs upgrade` has nothing new to do.

The full list is in the
[changelog](https://github.com/bn7ya/dbs/blob/main/CHANGELOG.md#083---2026-11-12). 0.8.3
includes everything in 0.8.1 and 0.8.2; coming from 0.8.0, read the
[0.8.1](https://github.com/bn7ya/dbs/blob/v0.8.1/RELEASE_NOTES.md) and
[0.8.2 release notes](https://github.com/bn7ya/dbs/blob/v0.8.2/RELEASE_NOTES.md) too. Coming
from 0.7.x, read the
[0.8.0 release notes](https://github.com/bn7ya/dbs/blob/v0.8.0/RELEASE_NOTES.md) first: they
say what 0.8 brings and how to upgrade.

**Nothing you use is removed or renamed, and one thing behaves differently on purpose.**
`django_dbs` typed alone **in a terminal** now opens the menu and exits 0 when you leave it;
it printed its help and exited 2. Where there is no terminal, in a script, a pipe or a
scheduler, it still prints the help and exits 2, and `django_dbs --help` is unchanged. Every
command, option, setting, REST route and MCP tool works as it did in 0.8.2, and your backups
restore with the same passphrase.
[Stability](https://github.com/bn7ya/dbs/blob/main/docs/stability.md) says what is covered.

## Added

- **The menu.** Its sections are Dashboard, Servers, Applications, Backups, Activity, Accounts
  and Manager, in the interface's light look and colours, under the DBS logo. The arrow keys
  move, Enter opens or runs, Esc goes back, Tab moves between the sections and the page, `/`
  filters a list, `?` lists the keys, and `q` or Ctrl+C leaves. Opening a server, an
  application, a backup or a plan lists what can be done with it, and an account is offered
  only what its role allows.
- **A form for every command.** An action opens a form with a field for each thing its command
  takes. A server, an application, a backup, a plan or a `.env` version is chosen from a list.
  The form shows the `django_dbs` command it will run, which is the line to put in a script,
  and **All commands** opens any command the same way.
- **A file explorer.** An application's **Files** opens its allowed folders: Enter opens a
  folder and Backspace goes up, `d` downloads the selected file, `u` uploads one, `n` makes a
  folder and `x` deletes. The same explorer chooses a folder on a server while an application
  is added, and a file or a folder on your own computer wherever a path is asked for.
- **Secrets and questions.** A server's SSH password, the passphrase of its key file and an
  application's backup passphrase are typed in their form, shown as dots, used for that one
  command and then forgotten. Your account password, yes or no, and the name typed out before
  a real restore, deploy, move or removal are asked in dialogs.
- **A running command** shows what it prints, its step, whether its connection is alive and
  how much it has moved. Ctrl+C stops the command, as it stops the typed one, and the menu
  stays open.
- **`django_dbs menu [--as NAME]`** opens the menu by name. On a new installation the menu
  makes the first account, the master.

The menu runs the commands' own code on the same data folder, so roles, passwords, typed names
and **Activity** are the same as for a typed command. `run`, `export` and the account commands,
opened from **All commands**, run as themselves in the terminal and come back to the menu;
`import` and `mcp` are named with the line to type.

## Changed

- **`django_dbs` typed alone in a terminal opens the menu.** A script that ran the bare
  command with a terminal attached and waited for it to return would now wait in the menu.
  Without a terminal nothing changes.

## Where it runs

The menu paints its own light look where the terminal shows 256 colours or more, keeps the
terminal's own colours where it shows fewer, and uses none with `NO_COLOR` set. It needs a
window of at least 64 columns by 18 rows, reads in English, and does not take the mouse, so
the terminal's own selection keeps working. It is tested on Linux, and macOS runs the same
code. On Windows it needs Windows Terminal or another console that understands escape
sequences; where the console does not, `django_dbs` alone prints its help as before.

## Upgrading

On the manager's machine:

```bash
pipx upgrade django-dbs
django_dbs
```

[The menu](https://github.com/bn7ya/dbs/blob/main/docs/manager.md#the-menu) in the manager's
guide describes each part. In a project, `pip install --upgrade django-dbs` is enough.
