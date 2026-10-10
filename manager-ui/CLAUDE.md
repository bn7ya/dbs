# manager-ui — the DBS manager's interface

The Angular source of the standalone DBS manager (`django_dbs run`). It is built once at release
into `dbs/manager/static/dbs_manager/` and shipped inside the wheel; Django serves it at `/` with
the assets under `/static/dbs_manager/`. A developer who installs `django-dbs` never needs Node.
The repository's own `CLAUDE.md` still governs: say "developer", never "end user", and never compare
DBS to another tool.

## Stack

Angular 22 (standalone, signals, zoneless, TypeScript 6), Angular Material 22 and the CDK, Font
Awesome Free from npm, Tajawal from `@fontsource/tajawal`. Unit tests are Vitest through
`@angular/build:unit-test`; journeys are Playwright. Nothing is fetched from the network at run
time: fonts, icons and styles are all in the bundle.

## Commands

```bash
npm ci
npm start                       # ng serve; /api is proxied to django_dbs run on 127.0.0.1:8765
npm run lint                    # ng lint, the Font Awesome Free check, the e2e type-check
npx ng test --watch=false       # Vitest, jsdom
npm run build:package           # production build into ../dbs/manager/static/dbs_manager
npx playwright test             # starts django_dbs run --no-browser --port 8799 --data-dir <tmp>
```

`scripts/build_manager_ui.sh` at the repository root runs `npm ci` and `npm run build:package`. The
built directory is gitignored. The Angular CLI needs Node 22.22.3+ or 24.15+.

## The package build

`angular.json` has a `package` configuration layered on `production`: `outputPath` is
`{"base": "../dbs/manager/static/dbs_manager", "browser": ""}` and `baseHref` is
`/static/dbs_manager/`, so the bundle and its fonts resolve under the static prefix. `app.config.ts`
provides `APP_BASE_HREF` as `/`, so router URLs stay at `/`, `/servers`, `/setup`. API calls are
absolute (`/api/...`) and unaffected by either.

## Hard rules

1. **One pattern: vertical slice.** One feature directory per page, flowing
   `Component → Store → Api → HttpClient`; each layer calls only the one below it. A component
   holding `HttpClient`, or a store holding presentation state, is the pattern broken.
2. **Standalone components only**, `OnPush`, and `.ts`, `.html`, `.scss` as three files. Never an
   inline `template:` or `styles:`.
3. **State is signals** (`signal`, `computed`, `linkedSignal`, `resource`). No `BehaviorSubject`
   for view state. Zoneless change detection is on; anything mutating state outside a signal does
   not render.
4. **No `setTimeout` or `setInterval`.** Model timing in state (`timer` + `exhaustMap` in
   `JobWatcher`, `afterNextRender`, `afterRenderEffect`).
5. **Every route has a guard.** Every one.
6. **Material for every interactive element.** A button is `matButton` (`filled`, `outlined`,
   `tonal`, or text) or `matIconButton`; a link that looks like a button is `<a matButton
   routerLink>`. A field is `mat-form-field` with `matInput`, `mat-select`, `mat-chip-grid`; choices
   are `mat-radio-group`, `mat-checkbox`, `mat-slide-toggle`, `mat-button-toggle-group`; lists are
   `mat-table` with `mat-paginator`; steps are `mat-stepper`; menus are `mat-menu`. Never
   `confirm()`, `alert()`, `prompt()`, `<dialog>` or a bare `<input type="radio">`: ask through
   `Confirmation`, report through `Toaster`, collect through `Dialogs`. A control two features need
   becomes a component in `shared/`, never a second copy.
7. **Features never restyle Material.** No `.mat-mdc-*` or `.mdc-*` selector, no `--mat-*`
   override, no `::ng-deep` in a feature. The theme is one file, `src/styles/_material.scss`:
   `mat.theme(...)` and `mat.*-overrides(...)` only. A feature stylesheet lays its page out and may
   size a Material host (`inline-size`, grid placement); how a component looks is a change to
   `_material.scss` or `_tokens.scss`, a decision for the whole app. A destructive button carries
   the `app-danger` class, which `_material.scss` defines.
8. **No raw px in feature styles.** Colour, type, spacing, radius, motion and elevation are
   `var(--app-*)` tokens from `src/styles/_tokens.scss`. `_layout.scss` holds page widths,
   dialog widths and breakpoints (`@use "layout" as *;`). Those two and `_reset.scss` are the only
   files exempt.
9. **Logical properties only** (`margin-inline-start`, `inset-inline-end`, `text-align: start`).
   Never `left`/`right`. Content renders in its own direction (`dir` on the content element, a
   `<bdi>` around a name), never on the row.
10. **Everything is typed.** No `any`; take `unknown` and narrow. Every `interface` and `type`
    alias lives in a sibling `<name>.types.ts`, imported with `import type`. `strictTemplates` is
    on.
11. **Nothing unused, nothing deprecated.** A function, import, style, translation key or file with
    no caller is deleted.
12. **Almost no comments.** No JSDoc, no `/* */` blocks. A comment is one or two lines saying *why*
    where the code cannot: a framework constraint, a deliberate choice. Lint pragmas are not
    comments. This file is where the code is described.
13. **Bilingual, plainly written.** Every user-facing string is in both `en.json` and `ar.json` with
    identical key sets; never a literal in a template. The Arabic is written from the meaning, with
    no tashkeel, no count before a noun, and a title that names the page. The backend sends codes,
    never prose: an error resolves as `errors.<code>`.
14. **Icons are Font Awesome Free**, `fa-solid` or `fa-regular`, always `aria-hidden="true"` beside
    text that names the action; an `<i>` is never the button. `scripts/check-icons.mjs` fails the
    lint on any icon the free set lacks, or a `fa-regular` icon with no free regular style. Glyphs
    do not mirror; where direction is the point, flip it under `[dir="rtl"]`.
15. **Never draw an SVG by hand.** An icon is Font Awesome; a picture comes from the developer.

## Layout

```
manager-ui/
  angular.json  package.json  tsconfig*.json  eslint.config.js  playwright.config.ts
  proxy.conf.json           /api → http://127.0.0.1:8765
  scripts/check-icons.mjs   every fa-* used exists in Font Awesome Free
  e2e/                      Playwright journeys; e2e/support/ is what they share
  src/
    styles/_tokens.scss     the --app-* tokens, light and dark through light-dark()
    styles/_material.scss   the one Material theme and its overrides
    styles/_layout.scss     page, dialog and nav widths, breakpoints
    styles/_reset.scss  _base.scss  _typography.scss  _dialog.scss  _table.scss
    styles.scss             cascade layers: reset, base, material, app
    app/
      app.{ts,html,scss}    the root: skip link, direction, router outlet
      app.config.ts         providers
      app.routes.ts         top-level routes
      core/                 auth, setup, i18n, http, jobs, the signed-in layout
      shared/               components and pipes more than one feature uses
      features/<feature>/   one directory per page
```

A feature directory:

```
features/<feature>/
  <feature>.routes.ts       lazy entry: guard, route-provided store, provideTranslations(en, ar)
  guards/<feature>.guard.ts
  pages/<page>/<page>.{ts,html,scss}
  components/<name>/        dialogs and pieces the feature's pages share
  state/<feature>.store.ts  signals; provided by the route, so state dies with the page
  data/<feature>.api.ts     one method per endpoint; the only HttpClient
  data/<feature>.types.ts   the backend contract, pagination envelope included
  i18n/{en,ar}.json
  testing/                  fixtures the specs share, never imported by the app
```

Path aliases: `@core/*`, `@shared/*`, `@features/*`, `@styles/*`.

## Conventions

**Theme.** `_material.scss` calls `mat.theme` with an orange primary and yellow tertiary palette,
`theme-type: color-scheme` (light and dark follow the operating system through `light-dark()`),
Tajawal through `--app-font-family` and density 0, then maps the system tokens (primary, error,
surface, outline, corners) onto the `--app-*` tokens. Form fields default to `outline` with dynamic
subscript sizing (`MAT_FORM_FIELD_DEFAULT_OPTIONS`). Look at a change in both colour schemes.

**Direction.** `LocaleStore` writes `lang` and `dir` on the document. `AppDirectionality` replaces
the CDK `Directionality` app-wide and follows `LocaleStore.isRtl()`, so dialogs, menus, snack bars
and steppers flip on a runtime language switch. `AppPaginatorIntl` translates the paginator.

**Fields.** A text field is `mat-form-field` + `mat-label` + `matInput`, a `mat-hint`, and a
`mat-error` shown through `[appFieldError]="message"` (`shared/field/field-error.ts`), which puts
the control in its error state while the message is non-empty. Validation lives in signals, not in
Angular validators, so the directive is how Material learns a field is wrong. A password is
`<app-password-input [label] [hint] [error]>`, a whole form field with a reveal toggle.

**Tables.** Every `mat-table` sits in `<div class="table-scroll">`: it keeps its columns on a narrow
screen and the wrapper scrolls sideways. The table carries `[attr.aria-label]`; its paginator sits
in a labelled `<nav>`.

**Busy buttons** are `[disabled]` with `aria-busy` and a `matButtonIcon` spinner before their text,
and the text says what is happening.

**Do not write a focus ring.** `_base.scss` draws one `:focus-visible` outline for the document.

**Errors.** The interceptor normalises every failure to `ApiError` (`{code, message, fields?}` from
the backend envelope `{"error": {...}}`). Stores hold it; pages render `{{ error | errorText }}`,
which reads `errors.<code>`, or `errors.checkFields` when `fields` is set. `message` is English for
API clients and is never printed. A 401/403 whose code is `not_authenticated` or
`authentication_failed`, outside `/api/auth/`, forgets the identity and goes to sign in.

**XHR, not fetch.** `provideHttpClient(withXhr(), …)`: only XHR reports upload progress.

**Jobs.** Work that outlives a request answers `202 {activity}`; `JobWatcher.watch(id)` reads
`/api/activity/{id}/` at once and then on a timer until the job is `succeeded` or `failed`. An
activity id is a number (the audit event's primary key); server, backup, plan and `.env` version ids
are UUID strings.

**Strings.** Feature bundles register on their route with `provideTranslations(en, ar)`. Shared and
core strings live in `core/i18n/{en,ar}.json`. Two bundles never define the same `errors.<code>`. A
missing key renders as itself. `t`, `errorText`, `appDate` and `fileSize` are impure pipes so a
language switch reaches text already on screen.

**Tests.** Import `describe`/`it`/`expect` from `vitest` and call `TestBed.resetTestingModule()` in
`afterEach`. Select Material controls through the CDK component harnesses
(`TestbedHarnessEnvironment`, `MatButtonHarness`, `MatDialogHarness`, `MatStepperHarness`, …) or by
role and label, never by `.mat-mdc-*` class. Pass
`{ provide: MATERIAL_ANIMATIONS, useValue: { animationsDisabled: true } }` when a spec opens an
overlay. Journeys select by role and accessible name, in both languages, from `e2e/support/copy.ts`.

## core

- **`AuthApi` / `AuthStore`** — `/api/auth/{csrf,login,logout,me}`. The store holds the identity as
  signals; `restore()` treats a refusal as signed out, `signIn()` primes CSRF first, `signOut()`
  always ends on `/sign-in`, `forget()` drops the identity without a request.
- **Guards** — `authGuard` (signed in, else `/setup` while no account exists, else `/sign-in?next=`),
  `guestGuard` (keeps a signed-in user off sign-in; `/setup` while no account exists),
  `groupGuard(...)`. The setup redirect keeps `?token=`.
- **`SetupApi` / `SetupStore` / `setupGuard` / `SetupPage`** — the first run. `check()` asks
  `GET /api/setup/` once and keeps the answer; `complete()` primes CSRF and posts the first account,
  closing the setup on success or on `setup_done`. `/setup` is open only while setup is needed. The
  page asks for the setup key only when the link lacks `?token=`, then username, password and its
  confirmation; on success it loads `/api/auth/me/` and opens `/`.
- **`SignInPage`** — username and password, follows `?next=`.
- **`AppLayout`** — the signed-in frame: a `mat-toolbar` header with the product name, the language
  switch and an account `mat-menu` holding About and sign-out; a `mat-nav-list` of `SECTIONS`
  (dashboard, servers, activity); the one `<main id="main">`. It provides `SHELL_FRAME`, so
  `StatusPage` knows it is inside.
- **`LocaleStore`, `TranslatePipe` (`t`), `ErrorTextPipe` (`errorText`), `provideTranslations()`,
  `LocaleSwitcher`** (a `mat-button-toggle-group`), **`AppDirectionality`, `AppPaginatorIntl`**.
- **`csrfInterceptor`, `errorInterceptor`, `apiErrorOf()`** — CSRF on unsafe requests; failures as
  `ApiError`.
- **`JobsApi`, `JobWatcher`** — follow a background job to its end.

## shared

- **`Dialogs`** — `open<R, D>(Component, { titleKey, data, size })` opens a component in a
  `MatDialog` framed by `DialogFrame` (translated title, close button) and returns
  `{ closed, whenClosed() }`; dismissal resolves `undefined`. The dialog component reads
  `injectDialogData<D>()` and `injectDialogRef<R>()` (`MAT_DIALOG_DATA.data`, `MatDialogRef`). A
  page that opens dialogs lists `providers: [Dialogs]`, so the dialog resolves the route's store.
- **`Confirmation.ask(options)`** — a `ConfirmDialog` (`role="alertdialog"`); resolves `true` on
  accept, `false` on reject or dismiss.
- **`Toaster.add({ severity, summary, detail? })`** — a `MatSnackBar` from `Toast`; a `danger` toast
  is announced assertively.
- **`Notice`** (`<app-notice severity closable (closed)>`) — an inline message; `role="alert"` for
  `warning` and `danger`, `role="status"` otherwise.
- **`StatusTag`** (`<app-status-tag severity icon label>`) — a state as icon and word, never colour
  alone.
- **`Skeleton`** — a CSS-only loading line. **`Breadcrumb`** (`<app-breadcrumb [items] [label] code>`)
  — a labelled trail of router links, the last one the current page.
- **`CopyButton`** (`<app-copy-button [text] [label]>`) — copies `text` to the clipboard and says so
  in a toast, or says to copy it by hand where the clipboard is unavailable.
- **`TimeAgoPipe`** (`timeAgo`) — "3 hours ago" through `Intl.RelativeTimeFormat`, Latin digits in
  both languages.
- **`PasswordInput`**, **`PasswordPrompt`** (asks for the account password and runs the guarded
  operation, retrying a wrong password in place), **`EmptyState`**, **`StatusPage`**,
  **`FieldError`**, **`AppDatePipe`**, **`FileSizePipe`**, **`uniqueId()`**.

## features

Every feature is mounted under `AppLayout` and its guard mirrors the backend's `IsAuthenticated`;
the backend permission is the boundary.

- **dashboard** (`/`) — every server as a card (check, health, last backup, next plan run, failures
  in the last 7 days, storage), the totals, recent failures, and a reminder to export when the last
  export is missing or older than 7 days. With no server it offers "Add a server".
- **servers** (`/servers`, `/servers/:serverId`) — list, search and page servers. The server page has
  a `mat-tab-nav-bar` (overview, backups, files, environment, activity) over the child route. The
  overview runs the connection check, shows the settings, edits them in a two-step dialog
  (connection, django-dbs and folders), re-pins a changed host key, reveals the backup passphrase
  behind the account password, links to the move, and deletes. Secrets are write-only; an edit that
  changes more than the name asks for the account password. Every path field in the dialog has a
  browse button.
- **server browser** (`components/server-browser/`, a dialog in the servers feature) — the server's
  folders and files as the SSH user sees them, through `ServerBrowserStore` (provided by the dialog
  itself) and `GET /api/servers/{id}/browse/`: Home, Up, a left-to-right trail, the projects
  discovery found as quick picks, a notice when the folder holds `manage.py`, and a paged
  `mat-table`, with a notice when the folder was cut at 5000 entries. In `folder` mode it closes with the folder on screen; in `file` mode a file row closes
  it with that file. `browseServer()` in `browse-server.ts` opens it for one path field and picks
  where it starts; the wizard and the edit dialog both call it.
- **server wizard** (`/servers/new`, in the servers feature) — a linear vertical `mat-stepper`:
  the optional connection snippet (`manage.py dbs connection --json`, parsed in
  `connection-snippet.ts`), address and host key (fingerprint compared with the snippet's), sign-in
  (create a key pair, paste a key, or a password; the server is created here, and a generated
  public key is shown to copy into `authorized_keys`), project (discovery runs on arrival, inside
  the snippet's folder when there is one; several projects found are a radio group, and choosing
  one, or one picked in the server browser, discovers inside it; the folders and `.env` sit behind
  "Show more settings", opened by itself when one of them has an error), check (runs on arrival;
  the two django-dbs versions must be compatible; when the saved Python cannot import django-dbs
  it shows the error and offers the Python discovery found with it, saved and re-checked in one
  click), the optional backup passphrase capture, and a test backup. Steps up to sign-in lock once
  the server exists. A discovery the developer did not ask for keeps a snippet's Python unless it
  found one that imports django-dbs. When discovery or "Use this Python" answers that the account
  password is required (the setup window is over), the wizard asks through `PasswordPrompt` and
  retries with it; that ask is kept out of the page's own notices.
- **redeploy** (`/servers/:serverId/move`) — move a server onto another one: target, django-dbs
  backup, `.env` version, folder archives, migrate and flush. A rehearsal needs no password; a real
  move needs the account password and the target's name typed out. The job's steps render as a list
  with a status each.
- **backups** (`/servers/:serverId/backups`) — plans (django-dbs, folders, or existing files
  collected from one folder) with a schedule and how many to keep here and on the server; files,
  newest first: take, upload with progress, download, verify, restore (rehearsal by default, the
  server name typed for a real one; optionally onto another server, whose name is then the one
  typed), delete with undo.
- **files** (`/servers/:serverId/files?path=`) — the server's allowed folders: a breadcrumb, open,
  download, upload, new folder, delete an empty folder or a file.
- **envfiles** (`/servers/:serverId/environment`) — versions of the server's `.env`: pull, show
  key names masked, reveal values behind the password, compare with the version before, push one
  back.
- **activity** (`/activity`, `/servers/:serverId/activity`) — the audit trail, newest first, with
  status and action filters; scoped to one server on its tab, which leaves out the account,
  sign-in and `manager.*` actions. An unknown action code renders as itself.
- **about** (`/about`, from the account menu) — the version, data folder, database, backups folder
  and last export, then the export, export with backups and import commands with copy buttons.

## API the interface calls

All JSON unless marked; lists are `{count, next, previous, results}` with one-based `page`.

| Method | Path | Body → answer |
|---|---|---|
| GET | `/api/setup/` | → `{needed}` |
| POST | `/api/setup/` | `{token, username, password}` → 201 `{username}`, signed in |
| GET | `/api/auth/csrf/` | sets the `csrftoken` cookie |
| POST | `/api/auth/login/` | `{username, password}` → `Identity` |
| POST | `/api/auth/logout/` | → 204 |
| GET | `/api/auth/me/` | → `Identity` |
| GET | `/api/dashboard/` | → `{servers, storage_bytes, last_export_at, recent_failures}` |
| GET | `/api/about/` | → `{version, data_dir, database, backups_dir, last_export_at}` |
| GET | `/api/servers/?search=&page=&page_size=` | → page of `ServerSummary` |
| POST | `/api/servers/` | `ServerCreate` (`host_key`, `generate_key?`, project fields) → `Server` with `public_key?`, `authorized_keys_hint?` |
| GET/PATCH/DELETE | `/api/servers/{id}/` | `ServerUpdate` → `Server` |
| POST | `/api/servers/fingerprint/` | `{host, port}` → `{key_type, line, fingerprint}` |
| GET | `/api/servers/{id}/public-key/` | → `{public_key}`; `no_private_key` on a password server |
| POST | `/api/servers/{id}/discover/` | `{project_dir?, account_password?}` → `Discovery` (fields, `dbs_version`, `is_project`, `candidates`); the password is required once setup is over |
| GET | `/api/servers/{id}/browse/?path=&page=&page_size=` | → `RemoteFolder` (`path`, `parent`, `home`, `project`, `truncated`, page of entries); no `path` is the home folder |
| POST | `/api/servers/{id}/passphrase/capture/` | `{}` → `{captured}` |
| POST | `/api/servers/{id}/check/` | → `Server` with `local_version`, `remote_version`, `installed`, `compatible`, `last_health`; the report adds `dbs_error` and `python_suggestion` |
| POST | `/api/servers/{id}/host-key/` | `{host_key, password}` → `Server` |
| POST | `/api/servers/{id}/passphrase/` | `{password}` → `{passphrase}` |
| GET | `/api/backups/?server=&page=&page_size=` | → page of `BackupFile` |
| POST | `/api/backups/take/` | `{server}` → 202 `{activity}` |
| POST | `/api/backups/upload/` | multipart `server`, `file` → 201 `BackupFile` |
| GET | `/api/backups/{id}/download/` | a link |
| POST | `/api/backups/{id}/verify/` | → 202 `{activity}` |
| POST | `/api/backups/{id}/restore/` | `{mode, rehearse, account_password?, server_name?, target_server?}` → 202 `{activity}` |
| DELETE | `/api/backups/{id}/` | → 204 |
| POST | `/api/backups/{id}/undo-delete/` | → `BackupFile` |
| GET/POST | `/api/backups/plans/` | `PlanCreate` → `BackupPlan` |
| PATCH/DELETE | `/api/backups/plans/{id}/` | `PlanUpdate` → `BackupPlan` |
| POST | `/api/backups/plans/{id}/run/` | → 202 `{activity}` |
| GET | `/api/files/{server}/?path=&page=&page_size=` | → `Listing` |
| GET | `/api/files/{server}/download/?path=` | a link |
| POST | `/api/files/{server}/upload/` | multipart `path`, `file` → 201 `Entry` |
| POST | `/api/files/{server}/folders/` | `{path, name}` → 201 `Entry` |
| DELETE | `/api/files/{server}/?path=` | → 204 |
| GET | `/api/envfiles/?server=&page=&page_size=` | → page of `EnvVersion` |
| POST | `/api/envfiles/pull/` | `{server}` → `{created, version}` |
| GET | `/api/envfiles/{from}/compare/?to=` | → `{from, to, added, removed, changed}` |
| POST | `/api/envfiles/{id}/reveal/` | `{password}` → `{content}` |
| POST | `/api/envfiles/{id}/push/` | `{password}` → `{version}` |
| GET | `/api/activity/?server=&action=&status=&page=&page_size=` | → page of `ActivityEntry` |
| GET | `/api/activity/{id}/` | → `Job`; `id` is a number |
| POST | `/api/redeploy/` | `{source_server, target_server, backup, env_version, archives, migrate, flush, rehearsal, password, confirm_name}` → 202 `{activity}` |

Errors arrive as `{"error": {"code", "message", "fields"?}}`. Setup answers `setup_done` (409),
`setup_token_invalid` (403), and `invalid` with `fields.password` codes from Django's password
validators (`password_too_short`, `password_too_common`, `password_entirely_numeric`,
`password_too_similar`).

## e2e

`playwright.config.ts` starts `django_dbs run --no-browser --port 8799 --data-dir <tmp>` (set
`E2E_BASE_URL` to use a running manager instead, `E2E_DATA_DIR` to choose the data dir). The `setup`
project runs `00-setup.spec.ts` first: it reads the one-time key from `<data dir>/setup.token` (or
`E2E_SETUP_TOKEN`) and creates the `ADMIN` account through the setup page. The `ltr` and `rtl`
projects depend on it. The journeys need an SSH fixture serving a Django project with django-dbs;
`e2e/support/config.ts` lists every knob as an environment variable. `09-redeploy` also needs a
second project on the fixture (`E2E_SSH_TARGET_PROJECT_DIR`, `E2E_SSH_TARGET_PYTHON`) and skips
without one. `tsconfig.e2e.json` type-checks them during `npm run lint`.
