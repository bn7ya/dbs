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

`scripts/test.sh` runs the load and scale suites short (`DBS_LOAD_BASELINE=5`,
`DBS_LOAD_AFTER=3`, `DBS_SCALE_ROWS=20000`). Other switches:

- `DBS_TEST_DB=postgres|mysql` runs the library suite on another database, and
  `DBS_MANAGER_DATABASE_URL` the manager suite.
- `DBS_LARGE_VALUE_MB` sets the size of the large-row tests (8 by default; 100 in CI), and
  `DBS_SLOW_TESTS=1` runs the slowest stream tests.
- `DBS_TEST_FULL_DISK=/mnt/tiny` points one isolation test at a small tmpfs, such as one of
  1 MiB, for a backup that fills a real disk.

## Against real servers

The SSH and container tests run against real servers when they are named:

```bash
sudo scripts/openssh_test_server.sh /tmp/dbs-sshd 2222 > ssh.env           # DBS_TEST_SSH_*
sudo scripts/container_fixture.sh docker /srv/dbs-live > containers.env     # or podman
set -a; . ./ssh.env; . ./containers.env; set +a
python -m pytest tests/test_ssh_openssh.py
python -m pytest tests/manager/live --ds=tests.manager.settings
```

`container_fixture.sh` builds a small Django project into an image with this checkout's wheel
and starts it with Compose as the SSH test account, rootless under Podman. The live tests add
the server and the application by its folder, back it up, restore it, deploy it, open a
terminal in its container, stream a backup from a read-only container, and rehearse moving the
server. `DBS_TEST_MOVE_PROJECT` names a host project to move, and
`DBS_TEST_MOVE_SUDO_PASSWORD` also moves it for real.

## Scripts

| Script | What it does |
|---|---|
| `scripts/load_backup.py --report-dir .` | Serves a small Django app under steady load, takes a panel backup and a streamed backup while it runs, and writes `load-report.md` and `load-report.json` (requests per second, latency percentiles, errors and memory). `--p95-factor` (or `DBS_LOAD_P95_FACTOR`, 2) is how much slower the 95th percentile may get |
| `scripts/upgrade_rehearsal.py` | Installs django-dbs 0.7.0 from PyPI in a new virtualenv, fills a project and a manager, upgrades both to this checkout and checks that nothing was lost; `--from-version` and `--keep` change where it starts and whether its folder stays |
| `scripts/stress_roundtrip.py` | Damages backups at random and checks they still restore (`DBS_STRESS_FLIPS` sets how many bytes) |
| `scripts/minimum_requirements.py` | Prints the lowest version of every dependency, for the lowest-dependencies CI job |
| `scripts/check_wheel.py dist/*.whl` | Checks a built wheel holds the manager's interface, its templates, the migrations and the console scripts |
| `scripts/train_base_model.py` | Regenerates the synthetic corpus behind the session guard's base model |

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
sudo scripts/openssh_test_server.sh /tmp/dbs-sshd 2222
sudo E2E_FIXTURE_SUDO=1 scripts/e2e_fixture.sh /srv/e2e docker > e2e.env
cd manager-ui && npm run build:package
set -a; . ../e2e.env; set +a; npx playwright test
```

`E2E_FIXTURE_SUDO=1` lets the test account use `sudo` with its password, which the real server
move needs; without it, that one scenario is skipped. The **Interface journeys** workflow runs
them on every push to `main` and every night.

## Releasing

1. Update `CHANGELOG.md` and `RELEASE_NOTES.md`, and add a step to `dbs/upgrade.py` for anything
   a developer must change in their project.
2. Set `version` in `pyproject.toml`.
3. When `main` is green, publish a GitHub release whose tag is `v` and the version, with
   `RELEASE_NOTES.md` as its body. The **Publish to PyPI** workflow runs CI, checks the tag
   against the version, builds the interface, the sdist and the wheel, and uploads them.
