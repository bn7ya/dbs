# manager-ui — the DBS manager's interface

The Angular source of the standalone DBS manager (`django_dbs run`). It is built once at release
into `dbs/manager/static/dbs_manager/` and shipped inside the wheel; Django serves it at `/` with
the assets under `/static/dbs_manager/`. A developer who installs `django-dbs` never needs Node.
The repository's own `CLAUDE.md` still governs: say "developer", never "end user", and never compare
DBS to another tool.

## Stack

Angular 22 (standalone, signals, zoneless, TypeScript 6), Angular Material 22 and the CDK, Font
Awesome Free from npm, Tajawal from `@fontsource/tajawal`, and `qrcode-generator` (MIT) for the
two-factor enrollment QR code. Unit tests are Vitest through `@angular/build:unit-test`; journeys
are Playwright. Nothing is fetched from the network at run time: fonts, icons, styles and the QR
code are all in the bundle. A new dependency goes into `THIRD_PARTY_LICENSES.md` in the same
commit.

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
provides `APP_BASE_HREF` as `/`, so router URLs stay at `/`, `/servers`, `/setup`, `/sign-in/code`.
API calls are absolute (`/api/...`) and unaffected by either.

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
5. **Every route has a guard.** Every one. A route a role may not use has a `capabilityGuard`, and
   an action a role may not take is wrapped in `*appCan="'capability'"`. Both only hide; the
   backend refuses with `role_required`.
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
    styles/_tokens.scss     the --app-* tokens: one light, blue scheme
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

## Routes

A server is an SSH host; an application is one Django project on it, on the host itself, in a
Compose service or in a container, under Docker or Podman. Every page that acts on a project
hangs off its application.

```
/                                    dashboard: every server with its applications
/servers                             servers, and host keys waiting for a person
/servers/new                         add a server: address and host key, sign-in, check
/servers/:serverId                   tabs: overview | applications | terminal | activity
/servers/:serverId/applications/new  add an application: folder, discovery, review, check, passphrase, test backup
/applications                        every application
/applications/:applicationId         tabs: overview | backups | schedule | files | environment | deploy | terminal | activity
/backups                             every application's backups and the storage they use
/console                             django_dbs commands as the signed-in account
/activity                            the audit trail
```

`routeParam(route, 'serverId' | 'applicationId')` (`core/routing/route-param.ts`) reads the
parameter from whichever ancestor route holds it. A tab that another feature provides is a
`loadChildren` of that feature's routes file: backups (`backups.routes.ts`, one application's
files; `plans.routes.ts`, its schedule; `all-backups.routes.ts`, the `/backups` page), files,
envfiles, redeploy (deploy in place and move), terminal (`data: {mode: 'server' |
'application'}`) and activity.

## Conventions

**Theme.** Blue, light and minimal. `_material.scss` calls `mat.theme` with a blue primary and
azure tertiary palette, `theme-type: light`, Tajawal through `--app-font-family` and density 0, then
maps the system tokens (primary and its container, error, surface and every surface container,
outline, corners) onto the `--app-*` tokens. Surfaces are white on a pale ground, flat, separated by
one-pixel outlines; `--app-shadow-1` is `none` and only menus and dialogs float. One blue accent marks
what can be acted on; status colours stay muted. A page has one filled button, its main action;
the rest are tonal, outlined or text. Form fields default to `outline` with dynamic
subscript sizing (`MAT_FORM_FIELD_DEFAULT_OPTIONS`).

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
`authentication_failed`, outside `/api/auth/`, forgets the identity and goes to sign in; a
`password_change_required` refusal reloads the identity and goes to `/password`.

**CSRF.** The interceptor sends the `csrftoken` cookie as `X-CSRFToken`. Behind a TLS proxy the
cookie is HttpOnly, so it asks `/api/auth/csrf/` once and keeps the token in `CsrfToken`, in
memory.

**XHR, not fetch.** `provideHttpClient(withXhr(), …)`: only XHR reports upload progress.

**Jobs.** Work that outlives a request answers `202 {activity}`; `JobWatcher.watch(id)` reads
`/api/activity/{id}/` at once and then on a timer until the job is `succeeded` or `failed`. While it
runs with a connection open, the job carries `connection: {state: alive|lost, last_activity_at,
bytes}`, which `JobConnection` renders. An activity id is a number (the audit event's primary key);
server, backup, plan and `.env` version ids are UUID strings; an account id is a number.

**Passwords before secrets.** Anything that decrypts on download, deletes, keeps fewer backups or
acts for real asks for the account password through `PasswordPrompt` (or a password field in the
form). A download that needs it trades the password for a one-time link (`{url}`, valid once for a
minute) that `Downloader` hands to the browser, so the file streams to disk.

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

- **`AuthApi` / `AuthStore`** — `/api/auth/{csrf,login,two-factor,two-factor/enrollment,
  two-factor/enrollment/confirm,password,recovery-codes,logout,me}`. The store holds the identity
  (role, capabilities, two-factor state, recovery codes left, password dates) and the sign-in
  `step` as signals; `can(capability)` and `forbids(capability)` read the capabilities;
  `restore()` treats a refusal as signed out, `signIn()` primes CSRF first and lands on the step the
  backend names, `signOut()` always ends on `/sign-in`, `forget()` drops the identity without a
  request.
- **Guards** — `authGuard` (signed in, else `/setup` while no account exists, else `/sign-in?next=`;
  a session whose password must change goes to `/password`), `guestGuard` (keeps a signed-in user
  off sign-in; `/setup` while no account exists), `stepGuard('code' | 'enroll')` (only while
  sign-in is at that step), `passwordGuard` (only while the password must change),
  `capabilityGuard(capability)` and `groupGuard(...)` (`/forbidden` otherwise). The setup redirect
  keeps `?token=`.
- **`Can`** (`*appCan="'servers.manage'"`) — renders its template only while the signed-in role
  has the capability.
- **`SetupApi` / `SetupStore` / `setupGuard` / `SetupPage`** — the first run. `check()` asks
  `GET /api/setup/` once and keeps the answer; `complete()` primes CSRF and posts the master
  account, closing the setup on success or on `setup_done`. `/setup` is open only while setup is
  needed. The page asks for the setup key only when the link lacks `?token=`, then username,
  password and its confirmation; on success it goes straight to `/sign-in/enroll`.
- **`SignInPage`** (`/sign-in`) — username and password, follows `?next=`, then the step the
  backend names. **`TwoFactorPage`** (`/sign-in/code`) — an authenticator code, or a recovery code.
  **`EnrollPage`** (`/sign-in/enroll`) — `QrCode` (drawn with `qrcode-generator`), the key as text
  to type by hand, a confirming code, then the ten `RecoveryCodes` shown once.
- **`PasswordPage`** (`/password`) — holds a session whose password expired, or whose new password
  the master asked for, until it changes it. **`AccountPage`** (`/account`, "Your account" in the
  account menu) — the role, when the password expires, `ChangePasswordForm`, and new recovery codes
  behind the password.
- **`AppLayout`** — the signed-in frame: a `mat-toolbar` header with the product name, the language
  switch and an account `mat-menu` holding Your account, About and sign-out; a `mat-nav-list` of
  `SECTIONS` (dashboard, servers, activity, and accounts for the master), each section shown only
  for its capability; the one `<main id="main">`. It provides `SHELL_FRAME`, so `StatusPage` knows
  it is inside.
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
- **`ConnectionDot`** (`<app-connection-dot [state] [lastSeenAt]>`) — a server's connection as a
  dot and a word: online, offline with when it was last seen, or not seen yet.
- **`JobConnection`** (`<app-job-connection [connection]>`) — a running job's connection as alive or
  lost, how much it moved and when the server last answered.
- **`Downloader.start(url)`** — follows a one-time download link with a temporary `<a download>`,
  so the browser streams the file to disk.
- **`PasswordPrompt`** — asks for the account password and runs the guarded operation, retrying a
  wrong password in place; `bodyValues` fill its text, `destructive` styles the submit as
  `app-danger`.
- **`isolated(text)`** — wraps a name in FSI … PDI so it keeps its own direction inside a sentence of
  either language.
- **`PasswordInput`**, **`EmptyState`**, **`StatusPage`**, **`FieldError`**, **`AppDatePipe`**,
  **`FileSizePipe`**, **`uniqueId()`**.

## features

Every feature is mounted under `AppLayout` and its guard mirrors the backend's `IsAuthenticated`
(and, for accounts, the master's capability); the backend permission is the boundary. Actions the
role cannot take are left out with `*appCan`.

- **dashboard** (`/`) — every server as a card (connection dot, check, health, last backup, next
  plan run, failures in the last 7 days, storage), the totals, recent failures, a reminder to export
  when the last export is missing or older than 7 days, and a warning when `key_store` says the
  sealing key sits in a file because no system keychain works. With no server it offers "Add a
  server".
- **accounts** (`/accounts`, master only) — every account with its role, status, two-factor state
  and password expiry; add one with a first password (`AccountForm`, `RoleChoice`); change a role
  (`RoleForm`); disable or enable; reset two-factor sign-in; ask for a new password; hand the master
  role over with the password and a code (`HandOverForm`).
- **servers** (`/servers`, `/servers/:serverId`) — list, search and page servers, with a Connection
  column. Above the list, the host keys Claude read and a person has not decided yet: address, key
  type, fingerprint and the command to compare it, with Confirm (asked once more) and Reject. The
  server page has a `ConnectionDot` in its header and a `mat-tab-nav-bar` (overview, backups, files,
  environment, activity) over the child route. The overview runs the connection check, shows the
  settings and whether the server has the `timeout` command, edits them in a two-step dialog
  (connection, django-dbs and folders), re-pins a changed host key (`HostKeyReview`,
  `HostKeyFacts`), reveals the backup passphrase behind the account password with a warning that it
  must never change, links to the move, and deletes behind the account password. Secrets are
  write-only; an edit that changes more than the name asks for the account password. Every path
  field in the dialog has a browse button. Where the project runs (on the server, or in a Docker Compose service with its
  service name and compose files) is `components/runtime-fields/`, which the dialog and the wizard
  share with `composeProblems()`; the check of a Compose server adds Docker Compose's version and
  whether the service is running, and what Docker said when it would not run.
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
  one, or one picked in the server browser, discovers inside it; a search that finds django-dbs in
  a Compose service switches the runtime to Compose with that service, and the services found are
  offered to pick from; the folders and `.env` sit behind
  "Show more settings", opened by itself when one of them has an error), check (runs on arrival;
  the two django-dbs versions must be compatible; when the saved Python cannot import django-dbs
  it shows the error and offers the Python discovery found with it, saved and re-checked in one
  click), the optional backup passphrase capture (warning that it must be read before the first
  backup and never changed), and a test backup. Steps up to sign-in lock once
  the server exists. A discovery the developer did not ask for keeps a snippet's Python unless it
  found one that imports django-dbs. When discovery or "Use this Python" answers that the account
  password is required (the setup window is over), the wizard asks through `PasswordPrompt` and
  retries with it; that ask is kept out of the page's own notices.
- **redeploy** (`/servers/:serverId/move`) — move a project onto a new server with the same
  environment: the new server, the backup to restore if this server does not answer (the newest,
  or none), the `.env` version and whether to replace the data. A rehearsal needs no password; a
  real move needs the account password and the new server's name typed out. The job's steps
  (`MoveSteps`) render as a list with a status each, with `JobConnection` while it runs and a note
  when the old server did not answer. A move that stopped after changing the new server offers
  "Revert the new server", rehearsed or real, with its own steps.
- **backups** (`/servers/:serverId/backups`) — plans (django-dbs, folders, or existing files
  collected from one folder) with a schedule, keeping 1 to 5 here (5 for a new plan) and 0 to 5 on
  the server (none for a new plan); an edit that keeps fewer asks for the password and says the next
  run deletes the oldest. Files, newest first: take, upload with progress, download, verify, restore
  (rehearsal by default, the server name typed for a real one; optionally onto another server, whose
  name is then the one typed), delete behind the password with undo. A django-dbs backup downloads
  through its plain link; a folder archive, a collected or an uploaded file through the password
  prompt and `Downloader`. A running take or restore shows `JobConnection`; a run whose connection
  broke says the backup is kept on the server and collected next time; a quarantined file shows its
  reason and is never offered for restore.
- **files** (`/servers/:serverId/files?path=`) — the server's allowed folders: a breadcrumb, open,
  download (the store asks the server for a link and prompts for the password only when the file
  holds secrets), upload, new folder, delete an empty folder or a file.
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
| POST | `/api/setup/` | `{token, username, password}` → 201 `{username, step}`, the master account, at the enroll step |
| GET | `/api/auth/csrf/` | → `{csrf_token}`; sets the `csrftoken` cookie |
| POST | `/api/auth/login/` | `{username, password}` → `{step}`, `code` or `enroll` |
| POST | `/api/auth/two-factor/` | `{code}` or `{recovery_code}` → `Identity` |
| POST | `/api/auth/two-factor/enrollment/` | `{}` → `{secret, uri, issuer, username}` |
| POST | `/api/auth/two-factor/enrollment/confirm/` | `{code}` → `{identity, recovery_codes}` |
| POST | `/api/auth/password/` | `{current_password, new_password}` → `Identity` |
| POST | `/api/auth/recovery-codes/` | `{password}` → `{recovery_codes}` |
| POST | `/api/auth/logout/` | → 204 |
| GET | `/api/auth/me/` | → `Identity` (with `role`, `capabilities`, `two_factor`, `recovery_codes_left`, `password_changed_at`, `password_expires_at`, `password_change_required`) |
| GET/POST | `/api/accounts/` | `{username, password, role}` → `Account[]` / 201 `Account`; master only |
| PATCH | `/api/accounts/{id}/` | `{role?, is_active?}` → `Account` |
| POST | `/api/accounts/{id}/two-factor/reset/` | → `Account` |
| POST | `/api/accounts/{id}/password/expire/` | → `Account` |
| POST | `/api/accounts/{id}/master/` | `{password, code}` → `Account`, the new master |
| GET | `/api/dashboard/` | → `{servers: [{id, name, host, check_status, checked_at, connection_state, last_seen_at, applications: [{id, name, kind, engine, check_status, checked_at, last_backup: {id, name, size, created_at, validation} \| null, next_plan_run, failures_7d, storage_bytes, health}]}], storage_bytes, last_export_at, recent_failures, key_store}` |
| GET | `/api/about/` | → `{version, data_dir, database, backups_dir, last_export_at, key_store}` |
| GET | `/api/servers/?search=&page=&page_size=` | → page of `ServerSummary` (`id, name, host, port, username, engines, application_count, last_check_status, last_checked_at, connection_state, last_seen_at, last_connection_error`) |
| POST | `/api/servers/` | `{name, host, port?, username, host_key, auth_method?: key\|password, private_key?, key_passphrase?, password?, generate_key?}` → `Server`, plus `public_key` and `authorized_keys_hint` when the key was generated |
| GET/PATCH | `/api/servers/{id}/` | `{name, host, port?, username, auth_method, private_key?, key_passphrase?, password?, account_password?}` → `Server` (`…ServerSummary`, `auth_method, has_private_key, has_key_passphrase, has_password, host_key, host_key_type, host_key_fingerprint, last_check_error, last_check_report, timeout_on_host, created_at, updated_at`) |
| DELETE | `/api/servers/{id}/` | `{account_password}` → 204; `server_has_applications` (409) while it runs any |
| POST | `/api/servers/{id}/check/` | → `Server`; `last_check_report` is `{system, engines: {docker\|podman: {installed, usable, version, compose, error}}, timeout}` |
| POST | `/api/servers/{id}/merge/` | `{into, account_password}` → `Server`, the one kept; refused unless both are the same machine |
| POST | `/api/servers/fingerprint/` | `{host, port}` → `{key_type, line, fingerprint}` |
| GET | `/api/servers/host-keys/?page=&page_size=` | → page of `HostKeyConfirmation` (`id`, `host`, `port`, `key_type`, `fingerprint`, `status`, `requested_at`, `expires_at`) |
| POST | `/api/servers/host-keys/{id}/confirm/` · `…/reject/` | `{}` → `HostKeyConfirmation` |
| GET | `/api/servers/{id}/public-key/` | → `{public_key}`; `no_private_key` on a password server |
| POST | `/api/servers/{id}/host-key/` | `{host_key, password}` → `Server` |
| GET | `/api/servers/{id}/browse/?path=&page=&page_size=` | → `RemoteFolder` (`path`, `parent`, `home`, `project`, `truncated`, page of entries); no `path` is the home folder |
| GET | `/api/applications/?server=&search=&page=&page_size=` | → page of `ApplicationSummary` (`id, name, server: {id, name, host, port, connection_state}, kind, engine, compose_service, container_name, project_dir, last_check_status, last_checked_at`) |
| POST | `/api/applications/discover/` | `{server, folder?, account_password?}` → `Discovery` `{folder, trusted, listing, engines, candidates, folders}`; the password is required once the server's setup window is over |
| POST | `/api/applications/` | `ApplicationSettings` + `server` → 201 `Application` |
| GET/PATCH | `/api/applications/{id}/` | `ApplicationSettings` + `account_password?` → `Application` |
| DELETE | `/api/applications/{id}/` | `{account_password}` → 204 |
| POST | `/api/applications/{id}/check/` | → `Application` + `{local_version, remote_version, installed, compatible}` |
| POST | `/api/applications/{id}/passphrase/` | `{password}` → `{passphrase}` |
| POST | `/api/applications/{id}/passphrase/capture/` | `{}` → `{captured}` |
| PUT | `/api/applications/{id}/deploy-steps/` | `{steps: DeployStep[], account_password}` → `Application`; field errors under `steps.N` |
| POST | `/api/applications/{id}/deploy/` | `{rehearsal, password?, confirm_name?}` → 202 `{activity}`; `no_deploy_steps` (409) without steps |
| GET | `/api/backups/?application=&page=&page_size=` | → page of `BackupFile` (`id, application, application_name, server, server_name, kind, name, size, sha256, validation, validated_at, failure, remote_path, taken_by, plan, plan_name, created_at`); without `application` every application's |
| POST | `/api/backups/take/` | `{application}` → 202 `{activity}` |
| POST | `/api/backups/upload/` | multipart `application`, `file` → 201 `BackupFile` |
| GET | `/api/backups/{id}/download/` | a link, for a django-dbs backup |
| POST | `/api/backups/{id}/download/` | `{account_password}` → `{url}`, a one-time link for a file the manager keeps encrypted |
| POST | `/api/backups/{id}/verify/` | → 202 `{activity}` |
| POST | `/api/backups/{id}/restore/` | `{mode, rehearse, account_password?, application_name?, target_application?}` → 202 `{activity}` |
| DELETE | `/api/backups/{id}/` | `{account_password}` → 204 |
| POST | `/api/backups/{id}/undo-delete/` | → `BackupFile` |
| GET/POST | `/api/backups/plans/?application=` | `PlanCreate` (`application, name, kind, paths?, pattern?, interval_minutes\|null, keep 1–5, keep_remote 0–5, enabled?, anchor_at?, time_zone?, account_password?`) → `BackupPlan` (`…, anchor_at, time_zone, next_run_at, last_run_at, last_status, last_error_code`) |
| PATCH/DELETE | `/api/backups/plans/{id}/` | `PlanUpdate` (`account_password` when it keeps fewer; `anchor_at` and `time_zone` move the beat) → `BackupPlan` |
| POST | `/api/backups/plans/{id}/run/` | → 202 `{activity}` |
| POST | `/api/backups/plans/{id}/reschedule/` | `{next_run_at}` (within a year) → `BackupPlan`; later runs follow from it |
| POST | `/api/backups/plans/{id}/pause/` · `…/resume/` | `{}` → `BackupPlan`; resuming picks the next beat after now; `manual_plan` for a plan without an interval |
| GET | `/api/files/{application}/?path=&page=&page_size=` | → `Listing` |
| POST | `/api/files/{application}/download/` | `{path, account_password?}` → `{url}`, a one-time link; the password is required for a `.env` |
| POST | `/api/files/{application}/upload/` | multipart `path`, `file` → 201 `Entry` |
| POST | `/api/files/{application}/folders/` | `{path, name}` → 201 `Entry` |
| DELETE | `/api/files/{application}/?path=` | → 204 |
| GET | `/api/envfiles/?application=&page=&page_size=` | → page of `EnvVersion` (`id, application, path, size, keys, source, created_at, taken_by`) |
| POST | `/api/envfiles/pull/` | `{application}` → `{created, version}` |
| GET | `/api/envfiles/{from}/compare/?to=` | → `{from, to, added, removed, changed}` |
| POST | `/api/envfiles/{id}/reveal/` | `{password}` → `{content}` |
| POST | `/api/envfiles/{id}/push/` | `{password}` → `{version}` |
| GET | `/api/activity/?server=&application=&action=&status=&page=&page_size=` | → page of `ActivityEntry` (`id, action, status, target, detail, error_code, ip, actor, server, server_name, application, application_name, connection, created_at, started_at, finished_at`); `server` covers the server and its applications |
| GET | `/api/activity/{id}/` | → `Job`; `id` is a number |
| POST | `/api/redeploy/` | `{source_application, target_application, backup, env_version, flush, rehearsal, password, confirm_name}` → 202 `{activity}`; `backup` may be null |
| POST | `/api/redeploy/{job}/revert/` | `{rehearsal, password, confirm_name}` → 202 `{activity}`; `job` is a move or a deploy that stopped after it changed the application |
| POST | `/api/console/` | `{line, password?}` → `{exit_code, output, activities, password_required, error_code}`; `console_busy` (429) while the account's last command runs |
| GET | `/api/terminals/` | → `{results: Terminal[]}` (`id, mode, server, application, label, container, cols, rows, closed`), this session's open terminals |
| POST | `/api/terminals/` | `{mode: server\|application, server?, application?, password, cols?, rows?}` → 201 `Terminal` |
| GET | `/api/terminals/{id}/output/?cursor=` | → `{data (base64), cursor, skipped, closed, reason, exit_status}`; waits up to 15 s for output |
| POST | `/api/terminals/{id}/input/` | `{seq, data}` → `{accepted}`; a repeated `seq` is ignored |
| POST | `/api/terminals/{id}/resize/` | `{cols, rows}` → `Terminal` |
| DELETE | `/api/terminals/{id}/` | → 204 |

`ApplicationSettings` is `{name, kind: host|compose|container, engine: ""|docker|podman,
compose_project, compose_service, compose_files, container_name, project_dir, workdir,
python_path, manage_path, settings_module, remote_backup_dir, mounts: [{type, source,
destination, rw}], file_roots, env_path, env_location: host|container, backup_passphrase?,
discovered?}`. `Application` returns those (never the passphrase) with `server`,
`has_backup_passphrase`, `last_check_status`, `last_check_error`, `last_checked_at`,
`last_check_report` (`{system, dbs_version, dbs_error, python_suggestion, backup_command, env_file,
roots, remote_backup_dir, container?, panel_schedule?: {enabled, mode}}`), `last_health`,
`timeout_in_container`, `deploy_steps`, `discovered_at`, `created_at`, `updated_at`.

A `Discovery` candidate is `{kind, engine, compose_project, compose_service, compose_files,
container_name, replicas, running, project_dir, workdir, python_path, python_paths, manage_path,
settings_module, remote_backup_dir, backup_dir_on_host, mounts, file_roots: [{path, on_host}],
env: [{path, location, source}], dbs_version, compatible, problems, score}`, best first; `problems`
holds codes (`container_not_running`, `dbs_missing`, `dbs_too_old`, `backup_dir_not_mounted`).
With no folder, or one that is not there, `folders` suggests project folders under the home
folder. `trusted: false` means the folder or its parent can be written by others, so nothing in
it was run.

A `DeployStep` is `{kind, options, timeout_minutes 1–120}`, at most twelve: `git_pull {remote?,
branch?}`, `compose_pull {services?}`, `compose_build {services?, pull?}`, `compose_up
{services?}`, `restart`, `systemd_user_restart {unit}`, `pip_install {requirements}`, `migrate`,
`collectstatic`. A deploy job's `detail.steps` lists `check`, `safety_backup`, `record_env`, one
entry per deploy step (`{step: kind, index}`) and `final_check`, each with a status; `before` and
`after` hold `{git_head?, image?}`.

Errors arrive as `{"error": {"code", "message", "fields"?}}`. Setup answers `setup_done` (409),
`setup_token_invalid` (403), and `invalid` with `fields.password` codes from Django's password
validators (`password_too_short`, `password_too_common`, `password_entirely_numeric`,
`password_too_similar`). A role that may not do something gets `role_required` (403); an expired
password `password_change_required`. Connection codes are `connection_lost`,
`remote_command_timed_out` and `server_settling`; a move adds `source_unreachable`,
`no_backup_to_rehearse` and `move_not_revertable`; a backup `backup_quarantined`, `stream_broken`,
`backup_lost_on_server` and `dbs_too_old`; a container `container_engine_missing`,
`engine_permission_denied` and `container_not_running`; a terminal `terminal_off`,
`too_many_terminals` (429), `terminal_closed` (410) and `terminal_not_found`.

## e2e

`playwright.config.ts` starts `django_dbs run --no-browser --port 8799 --data-dir <tmp>` (set
`E2E_BASE_URL` to use a running manager instead, `E2E_DATA_DIR` to choose the data dir). The `setup`
project runs `00-setup.spec.ts` first: it reads the one-time key from `<data dir>/setup.token` (or
`E2E_SETUP_TOKEN`), creates the `ADMIN` account through the setup page and enrolls it in two-factor
sign-in, keeping the key in the data dir (`E2E_ADMIN_TOTP_SECRET` supplies it for a manager set up
beforehand). Sign-ins take a fresh code per 30-second step under a file lock. The `ltr` and `rtl`
projects depend on it. The journeys need an SSH fixture serving a Django project with django-dbs;
`e2e/support/config.ts` lists every knob as an environment variable. `09-redeploy` also needs a
second project on the fixture (`E2E_SSH_TARGET_PROJECT_DIR`, `E2E_SSH_TARGET_PYTHON`) and skips
without one. `tsconfig.e2e.json` type-checks them during `npm run lint`.
