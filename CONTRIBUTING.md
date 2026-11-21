# Contributing to DBS

Thank you for helping. DBS looks after other people's data, so every change is held to two
promises: nothing a release offers breaks later, and nothing a developer backed up is lost.
Everyone taking part follows the [code of conduct](CODE_OF_CONDUCT.md).

## Issues and questions

Open an issue with one of its forms: a bug, a backup that does not validate, open or restore,
an enhancement, or the documentation. Questions and ideas still taking shape go to
[Discussions](https://github.com/bn7ya/dbs/discussions). [SUPPORT.md](SUPPORT.md) says where
each belongs. Never put a real backup, passphrase, `SECRET_KEY`, `.env` value or credential in
an issue.

## The stability promise

From 0.8.0 on, a change may add, and may not remove, rename or change what a released version
offers. When something has to work differently, add the new way beside the old one and keep the
old one working exactly as before. [docs/stability.md](docs/stability.md) is the promise to
developers; in short:

- **Backups always open.** Every backup written by 0.8.0 or later validates and restores, with
  the same passphrase, in every later release. Keep every format reader, `MAGIC`, the layout of
  every released format and the passphrase derived from `SECRET_KEY`. Nothing deletes or
  overwrites a backup.
- **The Python API** of `dbs`, `dbs.transports` and `dbs.engine`, and `dbs.exceptions`, keep
  their names, parameters, positions, defaults and fields. A new parameter is keyword-only with
  a default that keeps the old behaviour.
- **Commands, settings and their defaults** stay: every `manage.py dbs` and `django_dbs`
  command, option, argument, exit code and `--json` key, and every documented `DBS_*` setting
  and manager environment variable. Anything new is optional.
- **Migrations only add.** Never remove, rename or retype a field or a model, and never edit a
  released migration. Audit rows are never rewritten.
- **The manager** keeps its REST routes and fields, its MCP tools and their inputs, its data
  folder, and everything it sealed.
- **The only exceptions:** a bug fix that makes DBS do what its documentation says; a security
  fix, which may refuse what was unsafe but never deletes data; and dropping a Python or Django
  version after its end of life, in a minor release.

`tests/test_stability.py` and `tests/manager/test_stability.py` check all of this against
every release recorded in `tests/stability/`, and restore the golden backup each recorded. Never
edit, regenerate or delete a recorded release, and never change those tests to make a change
pass: change the code so it keeps the promise.

## The rules for code

[CLAUDE.md](CLAUDE.md) holds every rule for this repository, and they apply to people and AI
assistants alike: no comments outside the public API's docstrings, "developer" rather than "end
user", no comparisons with other tools, Python 3.9 syntax, Django 4.2 to 6.x, the security
invariants and the manager's constraints. [manager-ui/CLAUDE.md](manager-ui/CLAUDE.md) adds the
interface's rules. AI assistants read the same file as `AGENTS.md` (Codex, opencode, Copilot's
agent and the other harnesses that read it), `GEMINI.md` (Gemini CLI) and
`.github/copilot-instructions.md` (Copilot); `CLAUDE.md` is the one to edit, and the others are
copied from it.

Its section *How a change is made* is how every change is approached, by a person or an AI
assistant:

- Understand the request and the code it touches before changing anything.
- Find the function, or the few functions, the change belongs in, and change only those:
  enhance what is there, never rewrite, move or rename what the request did not name.
- Plan first. An AI assistant shows its plan and waits for approval before its first edit.
- Ask when the request leaves a gap; never fill it with an assumption.
- Keep the architecture. The backup and block code in `dbs/engine/`, `dbs/container/` and
  `dbs/crypto/` changes only when a request asks for that change by name.

## Making a change

1. Set up and run the tests, as in [docs/development.md](docs/development.md):

   ```bash
   pip install -e ".[dev]"
   scripts/test.sh
   ruff check .
   ```

2. Add tests with the change. A bug fix comes with a test that fails without it.
3. Write the change under `## [Unreleased]` in [CHANGELOG.md](CHANGELOG.md). Anything a project
   may want to do about it gets a step in `dbs/upgrade.py`, with a test, in the same commit.
4. A new dependency gets an upper bound below its next major version and a line in
   [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).
5. Open a pull request and answer its checklist.

## Security

Never report a security problem in a public issue or pull request; [SECURITY.md](SECURITY.md)
says how to report it privately.
