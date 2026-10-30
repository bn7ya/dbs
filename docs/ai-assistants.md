# AI assistants

DBS works with AI assistants in two ways: it gives a coding assistant accurate instructions
for your project, and it lets Claude operate the DBS manager through MCP.

## Instructions for a coding assistant

```bash
python manage.py dbs ai            # writes .claude/skills/django-dbs/
python manage.py dbs ai --agents   # also appends a DBS section to AGENTS.md
python manage.py dbs ai --check    # for CI: fails when the installed copy has drifted
python manage.py dbs ai --print    # prints the instructions instead of writing them
```

`--root DIR` writes them under another folder. The instructions ship inside the installed
package (`dbs/ai/`), so they always match the version you have, and `manage.py dbs upgrade`
refreshes an installed copy that is out of date.

## Claude and the DBS manager

`django_dbs mcp` is an MCP server, so Claude can fill the manager and look after the backups
for you. It runs on your machine, on the same data folder, and calls the same code as the
interface and the terminal, as one manager account and within that account's role.

```bash
claude mcp add dbs -- django_dbs mcp            # Claude Code
claude mcp add dbs -- django_dbs mcp --as sara  # when the manager has several accounts
```

For Claude Desktop, add it to `claude_desktop_config.json`:

```json
{ "mcpServers": { "dbs": { "command": "django_dbs", "args": ["mcp"] } } }
```

Use the full path to `django_dbs`, or `"command": "python", "args": ["-m", "dbs.manager",
"mcp"]`, if it is not on your `PATH`. Then ask, for example: *"add my server
shop.example.com, user deploy, find the application in /srv/shop and back it up"*.

### What Claude can do

- See the overview, servers, applications, backups, plans, activity, `.env` versions (key
  names only) and files.
- Add a server, with an SSH password, a key file on this machine (the manager reads the file;
  Claude only names it) or a new key, once **you** have confirmed its host key. Claude reads
  the key and shows you the fingerprint; you confirm it on the **Servers** page or with
  `django_dbs server confirm-host-key ID` in a terminal. Claude cannot confirm it itself, and a
  key waits ten minutes for you.
- Change a server's name or address; check servers and applications.
- Discover and add an application from a folder, as discovery found it. Claude may choose the
  candidate, the backup folder, the `.env` and the allowed folders, and may record the *How it
  runs* answers from a closed list, but never the application's Python, `manage.py`, folders,
  container or settings module.
- Store a new application's backup passphrase before its first backup.
- Take, verify and save backups, add and run plans, keep more backups, and keep `.env`
  versions.
- Rehearse a restore, a move, a deploy, a server move, or putting an application back after a
  move that stopped. A rehearsal changes nothing.

### What Claude cannot do

Reveal a passphrase or a `.env` value; restore, move an application or a server, deploy or
revert for real; give a `sudo` password; choose deploy steps; push a `.env`; make a plan keep
fewer backups; save a file the manager keeps encrypted; remove a server or an application;
delete backups or files; open a console or a terminal; or pin or re-pin a host key you did not
confirm.

The MCP server never takes your account password, so anything the interface protects with it
(changing a checked application's paths, archive and collect plans) comes back to you, in the
interface or the terminal. Everything Claude does is in **Activity**, under the account it acts
as.

An SSH password you give Claude passes through the conversation. Prefer a key file or a new key
when that matters to you.
