# Development

## Set up and test

```bash
pip install -e ".[dev]"          # everything DBS uses, and the test tools
scripts/test.sh                  # every suite below, each with its own settings
DBS_TEST_HOUR=3 pytest           # the guard scores time of day; pin it
ruff check .
```

`scripts/test.sh` runs the library suite, then each of these as its own session:

| Suite | Settings | What it covers |
|---|---|---|
| `tests/manager` | `tests.manager.settings` | The manager |
| `tests/isolation` | `tests.isolation.settings` | Panel jobs in real child processes, failing backups, several instances of one project on one database |
| `tests/scaling` | `tests.scaling.settings` | Two hundred applications on one manager, with plans due in the same minute |
| `tests/load` | `tests.load.settings` | A backup while a Django site is under load |
| `tests/scale` | `tests.scale.settings` | A thousand tables and a large table (`DBS_SCALE_TABLES`, 1,000; `DBS_SCALE_ROWS`, 1,000,000; `DBS_SCALE_MEMORY_MB`, 1024) |

Inside the library suite, `tests/checkpoints` runs two real projects in child processes: a
checkpoint around every `migrate`, going back two and three migrations, a restore's own
checkpoints, and a project that refuses another project's backup although both share a
`SECRET_KEY`. It runs on PostgreSQL and MySQL too, with `DBS_TEST_DB`.

`scripts/test.sh` runs the load and scale suites short (`DBS_LOAD_BASELINE=5`,
`DBS_LOAD_AFTER=3`, `DBS_SCALE_ROWS=20000`). Other switches:

- `DBS_TEST_DB=postgres|mysql` runs the library suite on another database, and
  `DBS_MANAGER_DATABASE_URL` the manager suite.
- `DBS_LARGE_VALUE_MB` sets the size of the large-row tests (8 by default; 100 in CI), and
  `DBS_SLOW_TESTS=1` runs the slowest stream tests.
- `DBS_TEST_FULL_DISK=/mnt/tiny` points one isolation test at a small tmpfs, such as one of
  1 MiB, for a backup that fills a real disk.

## Against real servers

The tests that need a real SSH server run against virtual machines. `scripts/vm.py` boots a
guest with QEMU from a pinned Ubuntu 24.04 cloud image, with KVM where the machine has it and
software emulation where it does not, and `scripts/vm_fixture.py` prepares guests for each
suite and prints the variables its tests read:

```bash
sudo apt-get install qemu-system-x86 qemu-utils                 # once

python scripts/vm_fixture.py ssh > ssh.env                      # one guest
set -a; . ./ssh.env; set +a
python -m pytest tests/test_ssh_openssh.py

python scripts/vm_fixture.py move > move.env                    # an old server and a bare new one
set -a; . ./move.env; set +a
python -m pytest tests/manager/live/test_relocation.py --ds=tests.manager.settings

python scripts/vm_fixture.py containers docker > containers.env # or podman
set -a; . ./containers.env; set +a
python -m pytest tests/manager/live/test_containers.py --ds=tests.manager.settings

python scripts/vm_fixture.py down                               # stop every guest
```

- **`ssh`** is one guest with the account `dbs-ssh`, reached with a key or a password.
- **`move`** is two guests. `old` runs a small Django project from this checkout's wheel; `new`
  has nothing installed. The test rehearses the move, then moves for real: the manager installs
  Python on `new` with `sudo`, carries the project, rebuilds its virtualenv, migrates and
  restores. It passes when `new` holds the same rows and the same applied migrations, its
  `.env` names the new folder, the application checks clean there, and `old` is as it was.
- **`containers`** is a guest with Docker, or rootless Podman, running the same project built
  into an image and started with Compose as the SSH account. The tests add the server and the
  application by its folder, back it up, restore it, deploy it, open a terminal in its
  container and stream a backup from a read-only container.

A guest keeps its disk, key and console log in `~/.cache/dbs-vm/guests/NAME` (`DBS_VM_STATE`),
beside the downloaded image (`DBS_VM_CACHE`). `python scripts/vm.py --help` lists the commands
that run something in a guest or copy a folder into it, and the variables that size a guest or
send it through a proxy. Without KVM a guest takes minutes to boot, and the move takes longer
still.

## Scripts

| Script | What it does |
|---|---|
| `scripts/vm.py` · `scripts/vm_fixture.py` | Boot virtual machines and prepare them for the tests [against real servers](#against-real-servers) |
| `scripts/load_backup.py --report-dir .` | Serves a small Django app under steady load, takes a panel backup and a streamed backup while it runs, and writes `load-report.md` and `load-report.json` (requests per second, latency percentiles, errors and memory). `--p95-factor` (or `DBS_LOAD_P95_FACTOR`, 2) is how much slower the 95th percentile may get |
| `scripts/upgrade_rehearsal.py` | Installs django-dbs 0.7.0 from PyPI in a new virtualenv, fills a project and a manager, upgrades both to this checkout and checks that nothing was lost; `--from-version` and `--keep` change where it starts and whether its folder stays |
| `scripts/stress_roundtrip.py` | Damages backups at random and checks they still restore (`DBS_STRESS_FLIPS` sets how many bytes) |
| `scripts/minimum_requirements.py` | Prints the lowest version of every dependency, for the lowest-dependencies CI job |
| `scripts/check_wheel.py dist/*.whl` | Checks a built wheel holds the manager's interface, its templates, its SQLite backend, the menu and the logo it draws, the migrations and the console scripts |
| `scripts/train_base_model.py` | Regenerates the synthetic corpus behind the session guard's base model |
| `scripts/stability_snapshot.py X.Y.Z` | Records a release in `tests/stability/X.Y.Z`: its API, commands, terminal, REST routes, MCP tools, settings, migrations and `--json` keys, a golden backup and sealed values. It refuses a release already recorded |

## Stability

From 0.8.0 on, a change adds and never removes, renames or changes what a release offers
([CONTRIBUTING.md](../CONTRIBUTING.md) lists the rules, and [Stability](stability.md) is the
promise to developers). `tests/test_stability.py` and, in the manager's suite,
`tests/manager/test_stability.py` compare the code with every release in `tests/stability/` and
restore each golden backup, whole and damaged. A failure there names what was removed or
changed: put it back, or add the new way beside it. A recorded release is never edited,
regenerated or deleted.

## Transactions

Every statement DBS sends to a database runs inside a transaction, and a transaction is never
left open while the manager waits for a server. `dbs/transactions.py` holds the two blocks:

```python
from dbs import transactions

with transactions.reading():      # statements that only read
    waiting = list(Lease.objects.filter(expires_at__lte=now))

with transactions.atomic():       # statements that write, and what must be true together
    audit.interrupt(events=stopped)
    Lease.objects.filter(name__in=expired).delete()
```

`reads` and `atomically` are the same as decorators, `reading_on("alias")` and
`atomic_on("alias")` name another database, and the manager also uses Django's
`transaction.atomic()` where it writes. Use `reading()` for anything that only reads: where
SQLite begins transactions with `IMMEDIATE`, as `dbs upgrade` recommends and the manager sets,
`atomic()` takes the database's write lock as it begins, and `reading()` does not.

`tests/transactions.py` is the guard, switched on for every test of every suite in
`tests/conftest.py`. A test fails with `TransactionRuleBroken`, naming the file and line, when
DBS sends a statement outside a transaction, or reaches a server through `SSHSession` or
`RemoteHost` while one is open. It does not count what Django's request handler, management
commands, authentication, sessions and cache send, what a released migration sends, what a
test or a project's own code sends, or a table change on a database that cannot roll one
back. A test that calls a piece of the backup on its own does it
as a backup does, inside `dbs.engine.backup.one_snapshot("default")`.

## The manager's interface

The interface lives in `manager-ui/` (Angular and Angular Material); `manager-ui/CLAUDE.md`
holds its rules. A developer who installs `django-dbs` from PyPI never needs Node: the built
interface ships inside the wheel. From a checkout:

```bash
scripts/build_manager_ui.sh      # npm ci, then build into dbs/manager/static/dbs_manager
```

For live reload, run `django_dbs run --no-browser --port 8765`, then `npm start` in
`manager-ui/`. In `manager-ui/`:

```bash
npm run lint                     # ESLint, the Font Awesome Free check, the journeys' type check
npx ng test --watch=false        # the unit specs
npm run build:package            # the production build into the package
```

### Interface journeys

`manager-ui/e2e/` holds Playwright scenarios, each one a piece of a developer's real work in
English and Arabic: the first run, signing in, adding a server and a host project, backups,
the schedule, files and `.env`, deploys, two projects on one server, the console, terminal and
activity, a Compose project, and a server move, rehearsed and real.

```bash
python scripts/vm_fixture.py e2e --mount /tmp/dbs-guest > e2e.env
cd manager-ui && npm run build:package
set -a; . ../e2e.env; set +a; npx playwright test
```

The servers of the journeys are one guest: it holds the two projects and the Compose service,
and its account may use `sudo` with its password, which the real server move needs. `--mount`
mounts the guest's files with `sshfs`, so a journey can read and change a file on the server;
without it those checks are skipped. The **Interface journeys** workflow runs them on every
push to `main` and every night.

## The menu

`dbs/manager/menu/` is what `django_dbs` opens when it is typed alone in a terminal. It holds
no logic of its own: a form is built from a command's parser, and running it calls the same
handler a typed command calls, with a session that asks in dialogs. Adding a command to
`dbs/manager/terminal/parsers.py` puts it in **All commands**; `tests/manager/menu/test_parity.py`
then asks `menu/meanings.py` to say what each new argument names (a server, an application, a
file on this computer and so on), so its field gets the right list. A secret a handler asks
for with `session.secret("…")` is listed there too, so the form has a masked field that
answers it.

`menu/kit/` reads keys and draws, with Python's standard library only, and imports nothing of
Django or the manager. Its colours are the interface's tokens, and a test keeps them equal to
`manager-ui/src/styles/_tokens.scss`. The logo is drawn from `dbs/static/dbs/logo.svg`.

```bash
python -m pytest tests/manager/menu --ds=tests.manager.settings
```

Most of those tests drive the menu through a stand-in terminal: keys go in and the screen
comes back as text, so a page is asserted the way a developer reads it.
`test_on_a_terminal.py` starts the real command on a pseudo-terminal, which Linux and macOS
have and Windows does not; the Windows console is tested through a stand-in for it.

## Releasing

1. Update `CHANGELOG.md` and `RELEASE_NOTES.md`, and add a step to `dbs/upgrade.py` for anything
   a project may want to do.
2. Set `version` in `pyproject.toml`.
3. Record the release, so every later one keeps it:
   `python scripts/stability_snapshot.py X.Y.Z`, and commit `tests/stability/X.Y.Z`.
4. When `main` is green, publish a GitHub release whose tag is `v` and the version, with
   `RELEASE_NOTES.md` as its body. The **Publish to PyPI** workflow runs CI, checks the tag
   against the version, builds the interface, the sdist and the wheel, and uploads them.
5. Once it is on PyPI, `python scripts/upgrade_rehearsal.py --from-version X.Y.Z` installs it,
   fills a project and a manager, and upgrades both to the checkout without losing anything.
