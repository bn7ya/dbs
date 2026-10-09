# Frontend memory

Narrows the root `CLAUDE.md` to the Angular side. Read `.claude/docs/design-pattern.md` §3 for the layering contract; this file is the map.

## Layout

```
frontend/
  angular.json  tsconfig*.json  eslint.config.js  playwright.config.ts
  proxy.conf.json           /api, /admin, /static, /media → backend:8000
  e2e/                      Playwright journeys
  src/
    styles/_tokens.scss     the `--app-*` tokens: colour, type, space, radius, shadow, motion
    styles/_layout.scss     page width + shell breakpoints — the only literal lengths
    styles/_reset.scss, _base.scss, _typography.scss, _dialog.scss, _fonts.scss
    styles.scss             cascade layers: reset, base, primeng, app
    app/
      app.{ts,html,scss}    the shell
      app.config.ts         providers
      app.routes.ts         top-level routes, one lazy entry per feature
      core/                 auth, i18n, http, the signed-in layout
      shared/               components used by more than one feature
      features/<feature>/   one directory per page (rule 13)
```

A feature directory:

```
features/<feature>/
  <feature>.routes.ts
  guards/<feature>.guard.ts
  pages/<page>/<page>.{ts,html,scss}
  state/<feature>.store.ts
  data/<feature>.api.ts
  data/<feature>.types.ts
  i18n/{en,ar}.json
  CLAUDE.md                 required (rule 3)
```

## The flow

```
Component  →  Store (signals)  →  Api  →  HttpClient
```

Each layer calls only the one below it. A component holding `HttpClient`, or a
store holding presentation state, is the pattern broken.

Feature stores are provided by the route, not `providedIn: 'root'` — the state
should die with the page. `AuthStore` and `LocaleStore` are root-provided because
the guards and the shell need the same instance.

## What the hook enforces

`.claude/hooks/guard-checks.py` runs after every edit and blocks:

- raw px in any `.scss` other than `_layout.scss` and `_reset.scss` (rule 12)
- `setTimeout` (rule 10)
- `confirm()`, `alert()`, `prompt()`, `<dialog>`, bare `<input type="radio">` (rule 9)
- a docstring, a JSDoc block or a comment over two lines, and `any` (rules 30, 31)

`eslint.config.js` catches the same things earlier, plus `BehaviorSubject`
imports (rule 8) and unused symbols (rule 5).

## Conventions

**Path aliases.** `@core/*`, `@shared/*`, `@features/*`, `@styles/*`. A relative
path climbing past two levels is a sign the import should be an alias.

**Styles.** Colour, type, spacing, radius, motion and elevation are `var(--app-*)`, from
`src/styles/_tokens.scss`. Logical properties only — `margin-inline-start`, never
`margin-left` — so RTL is free. No utility-class framework goes in alongside this, Tailwind
included (see `.claude/docs/design-pattern.md` §5).

`@use "layout" as *;` where a stylesheet needs the page width or a breakpoint
(`stylePreprocessorOptions.includePaths` puts `src/styles` on the path).

Every interactive element is a PrimeNG component (rule 9), themed once in `app.preset.ts` —
Aura with a brass primary, mapped from the `--app-*` tokens. A feature stylesheet lays its page
out; it never restyles a PrimeNG component: no `.p-*` selector, no `--p-*` override, no
`::ng-deep`. A change to how every button looks is a change to `app.preset.ts` or `_tokens.scss`.
The cascade layers are `reset, base, primeng, app`, so the reset is the weakest rule on the page.

A form control sits in `<app-field>` (`shared/field`); a dialog opens through `Dialogs`, a toast
through `Toaster` and a confirmation through `Confirmation` — never PrimeNG's own services.
Every `p-table` sits in `<div class="table-scroll">`: PrimeNG's table has no card layout for a narrow
screen, so it keeps its columns and the wrapper scrolls sideways instead of squeezing them.
A link that should look like a button is `<a class="p-button p-button-text" routerLink>`: v22
has no `pButton` directive.

**Do not write a focus ring.** `_base.scss` draws one `:focus-visible` outline for the whole
document. A component `outline` replaces it rather than adding to it.

Both colour schemes are live: every colour token is `light-dark(light, dark)` and the
document follows the operating system. **Look at a change in both.**

**Type.** Tajawal, self-hosted from `@fontsource/tajawal` through the build's `styles` in
`angular.json` — 400, 500 and 700, matching `--app-weight-regular/medium/bold`. The family
is `--app-font-family`; nothing else names a font.

**Icons.** Font Awesome 7 Pro, loaded as a kit script from `index.html`. It is
the icon set for everything written in a feature template:

```html
<i class="fa-solid fa-user" aria-hidden="true"></i>
```

The kit is configured webfont-side (`method: "css"`), so it injects a
stylesheet and the glyph renders on the `<i>` itself — nothing rewrites the
element into an `<svg>`. That makes it indifferent to when Angular renders, which
is what we want under zoneless. Being Pro, `fa-thin`, `fa-duotone` and
`fa-sharp` are available alongside the free styles; they stop working the day
the subscription does.

The kit has no auto-accessibility, so an icon is never self-describing: mark a
decorative one `aria-hidden="true"`, and give a meaningful one a translated
label on the element that carries the behaviour. An `<i>` is never the button.

Font Awesome glyphs do not mirror themselves. Prefer a glyph with no direction, and where
direction is the point, flip it under `[dir="rtl"]`.

**Strings.** Never a literal in a template. Feature bundles register on the
route with `provideTranslations(en, ar)`, so a feature's strings load with the
feature. A missing key renders as the key itself, on purpose.

**Errors.** The interceptor normalises every failure to `ApiError`. Stores hold it
and never inspect status codes; pages render `{{ error | errorText }}`, which reads
`errors.<code>` from the bundles. `error.message` is English for API clients and is
never printed (language.md rule 9).

**XHR, not fetch.** `provideHttpClient(withXhr(), …)` in `app.config.ts`. Fetch is Angular's
default and reports no upload progress, so an upload's bar would sit at nothing until the file had
arrived. There is no server-side rendering here, the one place XHR is on its way out. Removing
`withXhr()` breaks no test — the testing backend replaces both — only the bar.

**Zoneless.** `provideZonelessChangeDetection()` is on. Anything mutating state
outside a signal will not render. That is the point.

## PrimeNG license

PrimeNG 22 is licensed: a Community key (free for qualifying organisations, renewed yearly) or a
Commercial one. The key goes in `src/app/primeui-license.ts` as `PRIMEUI_LICENSE` and is registered by
`providePrimeNG({ license })` in `app.config.ts`. It is verified offline in the browser, so it is shipped
with the bundle by design. With it empty, every page shows PrimeNG's red "Invalid PrimeUI License"
banner. The license's terms forbid removing that mechanism: do not.

## Classes and methods at the root

**`App`** (`app/app.ts`) — the root: the skip link, the direction on the content, the router
outlet, and the one `<p-toast>` and `<p-confirmdialog>`. **`AppPreset`** (`app/app.preset.ts`) —
the PrimeNG theme. **`PRIMEUI_LICENSE`** (`app/primeui-license.ts`) — the license key string.
**`appConfig`** — zoneless change detection, the router with component input
binding, HTTP over XHR with the CSRF and error interceptors, and PrimeNG with its message and
confirmation services. **`routes`** — sign-in, the status
pages and the redirect; each feature adds one lazy entry. Per-module descriptions live in
`core/`, `shared/` and each feature's `CLAUDE.md`.

## e2e support

`e2e/` holds Playwright journeys; `e2e/support/` is what they share. Types sit beside each helper in `<name>.types.ts`.

**Journeys.** `01-shell` signs in, tries the wrong password, walks the shell, switches language, signs out, and checks a signed-out visitor meets a closed door in both the guard and the API. `02-add-server` adds a server through the wizard (comparing the host-key fingerprint as a person would), runs the connection check, reveals the backup passphrase with the wrong then the right password, deletes the server, and checks the server page's tab row on a server of its own. `03-backups` takes a one-off backup, lists, downloads, verifies, deletes and restores it, and uploads a file from disk. `04-plans` covers the three plan kinds: django-dbs (daily, keep two), folders (downloads as `.tar.gz`) and existing files (collects two `.sql.gz` once, then nothing new). `05-files` opens the allowed folder, enters `uploads`, downloads and reads `a.txt`, uploads, creates a folder, deletes both after confirming, and is refused (not crashed, not signed out) outside the allowed folders. `06-envfile` pulls the `.env` file, reads masked keys, shows and hides values with the password, pulls again unchanged, changes the file and pulls a new version, compares, pushes the earlier version back and finds the server file byte for byte as it was; it holds a lock for its run because both projects edit the one file. `07-activity` checks the activity list reads in plain words, the filters narrow it, and a server's tab shows only that server. `08-lockout` checks repeated wrong sign-ins are refused in words a reader can act on, using a throwaway username so the admin account stays unlocked.

**`support/api.ts`** (`Api`, `api.types.ts`) — the API as a journey's setup and cleanup use it: a server to run on, and everything left behind removed afterwards. Nothing a journey asserts goes through here. `Api.signIn` signs in as the admin and carries the session; `createServer(name, overrides)` makes a server pointed at the SSH fixture with the host key pinned the way the wizard pins it; `findServers(prefix)`, `backups(server)`, `plans(server)` and `activity(query)` list; `deleteServer(id)` removes the server and every plan and backup it still lists; `status(method, path)` is the raw status of a request with this session, for "the API refuses too" checks; `dispose()` closes it.

**`support/config.ts`** — everything the journeys need to know about the environment, each value an environment variable. Defaults describe the setup the journeys were written against: the stack on :4200, signed in as `admin`, an SSH server on 127.0.0.1:2222 serving this machine's own filesystem, with a Django project at /srv/e2e-app (django-dbs in its `.venv`, a `.env` and a media folder) and two `.sql.gz` dumps in /var/backups/e2e-existing. `SSH` describes that server (`fingerprint` is what `ssh-keygen -lf` prints, compared in the UI as a person would; `existingFiles` are the `*.sql.gz` names in the order the app lists them). `SSH_FS` is where the server's filesystem can be read from the runner, default `/`; set `E2E_SSH_FS=` (empty) when it is not reachable, and the assertions that need it are skipped with a reason. `SCREENSHOT_DIR` is where each page is saved in each direction.

**`support/copy.ts`** (`copy.types.ts`) — the words a reader sees in both languages, as accessible names or sentences read off the running app, never translation keys, so a test selects what a person reads and a copy change shows up here rather than as a loosened regex. `copyIn(lang)` returns the lookup.

**`support/fixtures.ts`** (`fixtures.types.ts`) — what every journey shares through the `journey` fixture: the language of its project (`lang`, `dir`), the copy in that language (`t`), `named(action, target, suffix)` for an action button named after its target, `unique(what)` for a readable name so two projects never collide, `signIn(page, user)` as a person does, `shot(page, name)` into one folder per run, `toast(page, key)` (the toast comes before the live region announcing the same text), `shown(scope, text)` (a table keeps a hidden card-shaped copy of each cell for narrow screens, so a text locator needs the visible one) and `dismissToasts(page)`. `plain(text)` strips the FSI and PDI marks the toast region puts around a name.

**`support/lock.ts`** — `acquireLock(name, staleAfterMs)` lets one journey at a time use a resource the projects share (the `.env` file on the SSH server, which the `ltr` and `rtl` runs would otherwise edit under each other). `mkdir` is atomic, so the directory is the lock; one older than `staleAfterMs` belongs to a run that died and is taken over. Returns the release function.

**`support/ssh-fs.ts`** — the SSH server's filesystem as seen from the runner: confirm what the app wrote, make a change the app should notice, and put everything back as it was. `readRemote`, `writeRemote`, `appendRemote`, `remoteExists`, `listRemote` and `remoteMtime` (ms) are no-ops returning `null` when `E2E_SSH_FS` is empty (`remoteReachable` is false and journeys skip those assertions with a reason). `folderSnapshot(path)` remembers a folder's names and its `restore()` removes whatever appeared since, returning the names. `scratchFile(dir, name, content)` makes a small file on the runner to upload through the browser.

## Commands

```bash
docker compose exec frontend npx ng build
docker compose exec frontend npx ng test --watch=false   # vitest, jsdom
docker compose exec frontend npx ng lint
docker compose exec frontend npx playwright test         # stack must be up
```

Unit tests are Vitest, not Karma — Karma is retired upstream and rule 4 says
nothing deprecated. Two consequences worth knowing: import `describe`/`it`/
`expect` from `vitest` explicitly, and reset the harness yourself in `afterEach`
with `TestBed.resetTestingModule()`, which Karma used to do for you.

Then look at the page in both languages. `dir="rtl"` is not a checkbox.

## Adding a slice

1. `features/<feature>/` with the layout above — the name matches the Django app.
2. Types first, in `data/<feature>.types.ts`, mirroring the backend contract, pagination
   envelope included. No other file declares an interface or type alias (rule 30).
3. Api → store → component → route → guard.
4. Both `i18n/en.json` and `i18n/ar.json`, registered with `provideTranslations`.
5. One lazy entry in `app.routes.ts`, with a guard (rule 11).
6. Write `features/<feature>/CLAUDE.md`. The `Stop` hook blocks finishing without it.
