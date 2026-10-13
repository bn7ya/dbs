# Third-party licenses

DBS is released under the [MIT License](LICENSE). It builds on the packages below, each under
its own license.

DBS vendors no Python package: pip installs each one from its own distribution, which carries
its own license text. The one place third-party code ships inside the `django-dbs` wheel is the
DBS manager's interface; its license texts travel with it in
`dbs/manager/static/dbs_manager/3rdpartylicenses.txt`.

Licenses are given as [SPDX identifiers](https://spdx.org/licenses/), read from each package's
own metadata and license files on 2026-10-13. A package can change its license between
versions, so the metadata of the version you install is what applies. This file is a summary to
help a developer review their dependencies; it is not legal advice.

## Installed with `pip install django-dbs`

The backup library itself: what a Django project needs to back up, restore and validate.

| Package | Required | License | What DBS uses it for |
|---|---|---|---|
| [Django](https://www.djangoproject.com/) | `>=4.2,<7` | BSD-3-Clause | The framework DBS runs in |
| [cryptography](https://github.com/pyca/cryptography) | `>=41,<51` | Apache-2.0 OR BSD-3-Clause | AES-256-GCM encryption and HKDF key derivation |
| [argon2-cffi](https://github.com/hynek/argon2-cffi) | `>=21.3,<26` | MIT | Argon2id key derivation from the passphrase |
| [reedsolo](https://github.com/tomerfiliba/reedsolomon) | `>=1.7,<2` | Unlicense OR MIT-0 | Reed-Solomon parity that repairs damaged blocks |

## Installed with an extra

Each extra adds what one part of DBS needs. `pip install "django-dbs[all]"` installs all three.

| Package | Required | Extra | License | What DBS uses it for |
|---|---|---|---|---|
| [scikit-learn](https://scikit-learn.org/) | `>=1.3,<2` | `guard` | BSD-3-Clause | The session guard's IsolationForest detector |
| [paramiko](https://github.com/paramiko/paramiko) | `>=3,<6` | `ssh`, `manager` | LGPL-2.1-or-later | The `dbs.transports` SSH and SFTP API, and the manager's connections to servers |
| [djangorestframework](https://www.django-rest-framework.org/) | `>=3.15,<4` | `manager` | BSD-3-Clause | The manager's REST API |
| [waitress](https://github.com/Pylons/waitress) | `>=3,<4` | `manager` | ZPL-2.1 | The web server behind `django_dbs run` |
| [tomli](https://github.com/hukkin/tomli) | `>=1.1.0,<3`, Python < 3.11 only | `manager` | MIT | Reading a `dbs-client.toml` for `django_dbs server import-profiles` |

### Brought in by those packages

The exact set depends on the versions pip resolves. This is the set for the newest releases on
2026-10-13.

| Package | Brought in by | Installed with | License |
|---|---|---|---|
| asgiref | Django | `django-dbs` | BSD-3-Clause |
| sqlparse | Django | `django-dbs` | BSD-3-Clause |
| tzdata (Windows only) | Django | `django-dbs` | Apache-2.0 |
| cffi | cryptography, argon2-cffi-bindings, PyNaCl | `django-dbs` | MIT-0 from 2.1, MIT before |
| pycparser | cffi | `django-dbs` | BSD-3-Clause |
| argon2-cffi-bindings | argon2-cffi | `django-dbs` | MIT |
| typing_extensions (Python < 3.11 only) | asgiref, cryptography | `django-dbs` | PSF-2.0 |
| numpy | scikit-learn, scipy | `guard` | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 |
| scipy | scikit-learn | `guard` | BSD-3-Clause |
| joblib | scikit-learn | `guard` | BSD-3-Clause |
| cloudpickle | joblib (1.6 and later) | `guard` | BSD-3-Clause |
| threadpoolctl | scikit-learn | `guard` | BSD-3-Clause |
| narwhals | scikit-learn (1.9 and later) | `guard` | MIT |
| bcrypt | paramiko | `ssh`, `manager` | Apache-2.0 |
| PyNaCl | paramiko | `ssh`, `manager` | Apache-2.0 |
| invoke | paramiko (recent releases) | `ssh`, `manager` | BSD-2-Clause |

The binary wheels of numpy and scipy also carry the native libraries they link against, each
named with its license in the wheel's own `LICENSE.txt`. The Linux wheels, for example, carry
OpenBLAS (BSD-3-Clause), LAPACK (BSD-3-Clause-Open-MPI), the GCC runtime library
(GPL-3.0-or-later WITH GCC-exception-3.1) and libquadmath (LGPL-2.1-or-later).

## Bundled in the DBS manager's interface

The interface is compiled at release time into `dbs/manager/static/dbs_manager/` and ships
inside the wheel, so a developer never needs Node. These packages end up in that bundle, as
listed by the build's own `3rdpartylicenses.txt`, at the versions locked in
`manager-ui/package-lock.json`:

| Package | Version | License |
|---|---|---|
| @angular/core, @angular/common, @angular/forms, @angular/router, @angular/platform-browser | 22.1.0 | MIT |
| @angular/cdk, @angular/material | 22.2.2 | MIT |
| rxjs | 7.8.2 | Apache-2.0 |
| tslib | 2.8.1 | 0BSD |
| @fortawesome/fontawesome-free | 7.3.1 | CC-BY-4.0 AND OFL-1.1 AND MIT: icons under CC BY 4.0, fonts under the SIL OFL 1.1, code under MIT |
| @fontsource/tajawal (the Tajawal typeface) | 5.3.0 | OFL-1.1 |

`manager-ui/package.json` also declares @angular/compiler and zone.js (both MIT). The
production build compiles ahead of time and runs without zone.js, so neither is in the bundle.

## Development only

None of these is installed with `django-dbs`.

`pip install -e ".[dev]"` installs the `all` extra above and these:

| Package | License |
|---|---|
| pytest | MIT |
| pytest-django | BSD-3-Clause |
| pytest-cov | MIT |
| coverage | Apache-2.0 |
| ruff | MIT |
| pluggy, iniconfig | MIT |
| packaging | Apache-2.0 OR BSD-2-Clause |
| Pygments | BSD-2-Clause |
| exceptiongroup (Python < 3.11 only) | MIT |
| colorama (Windows only) | BSD-3-Clause |

The PostgreSQL test jobs also install `psycopg[binary]>=3`, under LGPL-3.0-only, and the MySQL
test jobs install `mysqlclient`, under GPL-2.0-or-later. Neither is a dependency of
`django-dbs`; a project installs the database driver it uses.

`npm ci` in `manager-ui/`, to build and test the interface:

| Package | License |
|---|---|
| @angular/build, @angular/cli, @angular/compiler-cli | MIT |
| typescript | Apache-2.0 |
| eslint, @eslint/js, angular-eslint, typescript-eslint | MIT |
| vitest, jsdom | MIT |
| @playwright/test | Apache-2.0 |
| @types/node | MIT |

Across all 587 packages locked in `manager-ui/package-lock.json`, counting platform-specific
optional builds: MIT (485), Apache-2.0 (29), ISC (27), BSD-2-Clause (18), MPL-2.0 (12, the
lightningcss CSS compiler and its platform builds), BSD-3-Clause (7), MIT-0 (2),
BlueOak-1.0.0 (2), and one each of CC-BY-4.0 (caniuse-lite's browser data), CC0-1.0
(mdn-data), 0BSD (tslib), OFL-1.1 (Tajawal) and Font Awesome Free's combined license. Only the
packages in the bundle table above ship in the wheel.

## What the licenses ask

- **MIT, BSD, Apache-2.0, ISC, ZPL-2.1, PSF-2.0, BlueOak-1.0.0:** keep the copyright and license
  notices when you redistribute the package. Apache-2.0 also asks that its `NOTICE` file, if
  the package has one, be kept.
- **0BSD, MIT-0, Unlicense, CC0-1.0:** no conditions.
- **LGPL-2.1-or-later (paramiko):** DBS imports paramiko as a separately installed, unmodified
  library. A modified paramiko that you distribute falls under the LGPL itself.
- **CC BY 4.0 (Font Awesome Free icons):** attribution is required. `3rdpartylicenses.txt`
  carries it inside the wheel, and the README's License section credits Font Awesome.
- **SIL OFL 1.1 (Font Awesome and Tajawal fonts):** the fonts may be bundled and redistributed
  with software; they may not be sold on their own.

## Keeping this list current

For the Python packages, in a fresh virtual environment:

```bash
pip install "django-dbs[all]" pip-licenses
pip-licenses --from=mixed --with-urls --ignore-packages pip-licenses prettytable wcwidth
```

For the interface, `scripts/build_manager_ui.sh` writes
`dbs/manager/static/dbs_manager/3rdpartylicenses.txt`, and `scripts/check_wheel.py` fails a
wheel that does not carry it.
