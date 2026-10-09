# core

What every feature depends on. **Not a feature** — no route of its own beyond
sign-in and the signed-in layout, no Django app mirroring its name.

Something belongs here only if a feature could not function without it. If two
features happen to use it, that is `shared/`. If one feature uses it, it belongs
in that feature.

## What lives here

```
core/
  auth/
    data/auth.types.ts      Identity — mirrors IdentitySerializer
    data/auth.api.ts        /api/auth/{csrf,login,logout,me}
    state/auth.store.ts     root-provided; who the user is
    guards/auth.guard.ts    authGuard, guestGuard, groupGuard(...)
    pages/sign-in/          the sign-in page
  i18n/
    locale.store.ts         current language, the dictionary, the direction
    locale.types.ts
    translate.pipe.ts       {{ 'key' | t }}
    error-text.pipe.ts      {{ apiError | errorText }}, errorText() for toasts
    provide-translations.ts feature bundles register on their route
    locale-switcher/        a p-selectbutton pair, not radios (rule 9)
    {en,ar}.json            application-wide strings and shared error codes
  layout/
    app-layout/             the signed-in frame: header, p-menu navigation, the one <main>
    shell-frame.ts          SHELL_FRAME — the token the frame provides so a page knows it is inside
  http/
    api.types.ts            Page<T>, PageQuery, ApiError
    api-error.ts            apiErrorOf() — the ApiError a resource failed with, for a store
    csrf.interceptor.ts     X-CSRFToken on unsafe requests
    error.interceptor.ts    every failure normalised to ApiError
  jobs/
    job.types.ts            Job, JobStarted, isFinished() — mirrors the activity entry
    jobs.api.ts             GET /api/activity/{id}/
    job-watcher.ts          JobWatcher.watch(id) — follows a background job to its end
```

Its backend counterpart is `backend/apps/accounts/` — mounted at `/api/auth/`.

## Classes and methods

**`AuthApi`** (`auth/data/`) — the four calls under `/api/auth/`: prime the CSRF cookie,
sign in, sign out, and ask who the user is.

**`AuthStore`** (`auth/state/`) — who the user is, application-wide, as signals: the
identity, whether it has been resolved yet, busy, the last error, the groups and a display
name.
- `restore()` asks the backend on boot; a refusal means signed out, not an error.
- `signIn()` primes CSRF, signs in and reports success; `signOut()` always ends signed out
  on the sign-in page.
- `hasGroup()`, `hasAnyGroup()`, `hasPermission()` decide what to show — superusers pass
  every check, as on the backend (`has_group` in `AccountService`).
- `forget()` clears the identity without a request, because the backend already ended the
  session; the error interceptor calls it before sending the user to sign in.

**Guards** (`auth/guards/`) — `authGuard` sends a signed-out visitor to sign in with a
return path; `guestGuard` keeps a signed-in user off sign-in; `groupGuard(...)` also
requires one of the named groups, or goes to `/forbidden`.

**`SignInPage`** (`auth/pages/sign-in/`) — the sign-in form: validates both fields, toggles
password visibility, signs in through the store and follows `?next=`.

**`AppLayout`** (`layout/app-layout/`) — the frame every signed-in page routes through: the
header with the product name, the signed-in name, the language switch and sign out; a `p-menu`
of the sections; and the page's one `<main id="main">`. It provides `SHELL_FRAME`. A slice with
a top-level page adds one entry to `SECTIONS`.

**`LocaleStore`** (`i18n/`) — the current language, persisted, and the dictionary of every
registered bundle. Writes `lang` and `dir` on the document. `translate()` resolves a key and
fills `{name}` placeholders; a missing key renders as itself. `register()` adds a feature's
bundles. `has()` says whether a key resolves in the current language — `translate()` returns a
missing key as itself, so `errorText` asks first and falls back to the generic message.

**`primeTranslation()`** (`i18n/primeng-translation.ts`) — builds PrimeNG's own strings (paginator
labels, rows per page, the empty message, the close label) from the `components.*` keys; `App` applies it
whenever the language changes.

**`TranslatePipe`** (`t`) — `translate()` in a template, as `{{ 'key' | t: { name } }}`; impure
so a language switch reaches text already on screen. **`provideTranslations()`** registers a feature's bundles when its
route activates. **`LocaleSwitcher`** — the two-language toggle, a `p-selectbutton`.

**`csrfInterceptor`** (`http/`) — sends Django's CSRF token on unsafe requests. Auth is a
same-origin session cookie, so CSRF is the price, and the built-in Angular option skips
absolute URLs and uses other names. **`errorInterceptor`** — turns every failure into an
`ApiError`, and sends the user to sign in when a 401 or 403 carries `not_authenticated` or
`authentication_failed` outside `/api/auth/`; any other refusal is about the request and stays on
the page. Without an envelope a 404 reads `not_found` and a 413 `upload_too_large`.

**`ErrorTextPipe`** (`errorText`, `i18n/error-text.pipe.ts`) — `{{ error | errorText }}` for an
`ApiError` or one field code. `errorKey()` gives the bundle key (`errors.<code>`, `errors.checkFields`
when `fields` is set, `errors.generic` for an unknown code); `errorText()` is the same for a toast
or dialog. The backend sends codes, so `ApiError.message` is never read.

**`apiErrorOf()`** (`http/api-error.ts`) — the `ApiError` a resource failed with: a resource wraps
a thrown plain object in an `Error` whose `cause` is the original; anything else reads `unknown`.

**`JobWatcher`** (`jobs/`) — `watch(id)` follows a background job: read at once, then every
`JOB_POLL_MS`; the last value is the finished job, then it completes; a failed read ends it with the
`ApiError`. **`JobsApi`** — `GET /api/activity/{id}/`, no polling. **`Job`**, **`JobStarted`**,
`isFinished()` — the activity entry a follower needs, and the `202` answer that starts one.

**Routes** (`app/app.routes.ts`) — every route has a guard. Signed-in pages are children of
`AppLayout` behind `authGuard`; a slice mounts one lazy `loadChildren` entry there and owns its own
`*.routes.ts`, whose root route carries the feature's guard and providers.

## Decisions worth not re-litigating

**Auth lives in `core/`, not `features/auth/`.** This is the documented
exception to rule 13's name mirroring. Guards and the HTTP interceptor need
`AuthStore`, and neither may import from a feature. A *page* built on auth — a
profile screen, user administration — is a normal slice with a mirrored name.

**Session cookies, not tokens.** Same-origin in both environments, so an
`HttpOnly` session cookie works and cannot be read by injected script. The price
is CSRF, which `csrfInterceptor` and `/api/auth/csrf/` pay.

**The three guards share `ensureSignedIn()`, a plain function.** `CanActivateFn`'s
return type includes `Observable`, which does not narrow — so a guard that calls
another guard cannot check the answer. Composing the helper instead of the guard
keeps `groupGuard` type-safe.

**`AuthStore.resolved` exists so guards do not act too early.** On a cold load
nobody has called `/me/` yet; without the flag, `authGuard` would bounce a
signed-in user to sign-in on every refresh.

**Group and permission checks here are convenience (rule 21).** They decide what
is *shown*. What a user may *do* is decided by `permission_classes` on the
endpoint, on every request. A guard without a matching backend check is
decoration, and shipping one is a security finding.

**A missing translation renders as its key.** Silently blank text hides the bug
until a user finds it.

**`t` and `errorText` are impure pipes.** A pure pipe is memoised on its arguments,
and the key does not change when the language does: the view re-renders on a locale
switch and the pipe hands back the string it cached in the old language.
`translate.pipe.spec.ts` pins it. Under zoneless OnPush a pass only runs when a
signal the view read has changed, so the cost is one map lookup per binding then.

**Errors read as `errors.<code>`, never as `ApiError.message`** (language.md rule 9).
`errorText` resolves the code and falls back to `errors.generic` for a code no bundle
has yet — `LocaleStore.has()` is what lets it tell. An error that carries `fields`
reads as `errors.checkFields`, with each field's code under its own control; a
`non_field_errors` code is the summary itself. Codes shared by many features live
here; a feature's own codes live in its bundle under `errors.*`. A code belongs here as soon
as a page outside its feature shows it: the SSH codes (`host_key_changed`, `ssh_unreachable`,
…) moved here when `/activity` began listing failed server operations, since that page loads
without the servers bundle. Two features never define the same `errors.<code>`: every registered
bundle merges into one dictionary, the last registered wins, and the text would change with the
order pages were visited — which is why `name_taken` moved here once backup plans showed it too.

**Every signed-in page goes through `AppLayout`.** `app.routes.ts` mounts the
features as children of one `''` route with `authGuard`, so the shell, its skip link
and the one `<main>` are there for all of them, and the root `App` stays thin.
The navigation is a `p-menu` whose items carry `routerLink`, so each destination is a real
link that opens in a new tab and marks the current page. A slice with a top-level page adds
one entry to `SECTIONS`.

**`StatusPage` serves both frames.** Inside the shell it is a plain block; standing
alone (`/forbidden`) it is the `<main>` and holds its own gutter. It tells which by
injecting `SHELL_FRAME` optionally, which `AppLayout` provides.

**`JobWatcher` is the one way a store follows a background job.** Work that outlives a request
(a backup, a verification) answers `202 {activity}`, and the activity entry is the job.
`watch(id)` reads it at once and then every `JOB_POLL_MS` (`timer` + `exhaustMap`, never
`setTimeout`), and completes after the finished job — `succeeded` or `failed` is a value, not an
error; only a failed read errors. A store pipes the start into it and takes `last()`:

```ts
this.api.take(server).pipe(
  switchMap(({ activity }) => this.jobs.watch(activity)),
  last(),
  finalize(() => /* clear the busy flag */),
  takeUntilDestroyed(this.destroyRef),
).subscribe(…);
```

`exhaustMap`, not `switchMap`: a read slower than the interval is waited for rather than cancelled
by the next tick. `Job` is declared here, not imported from `features/activity`, because core
never imports a feature. A job's `error_code` resolves through `errorText` like any other code.

**The error interceptor redirects only when the session is gone.** That is a 401 or
403 whose code is `not_authenticated` or `authentication_failed`, outside `/api/auth/`.
Every other 401 or 403 is about the request — `path_outside_roots`,
`remote_permission_denied`, `permission_denied` — and goes to the caller like any error, so
the page says it where it happened; redirecting on those would send a reader who opened a
refused folder to sign in. A 403 with no envelope is not read as a lost session either.
Under `/api/auth/` a refusal means wrong credentials, and redirecting there would loop. On
a lost session the interceptor calls `AuthStore.forget()` before navigating: the sign-in
page's `guestGuard` turns a signed-in user away, and the store would still say signed in.
`error.interceptor.spec.ts` pins all of it.

A 404 without the error envelope — a URL Django's resolver rejected before DRF saw it — is
still normalised to `not_found`, and a 413 without one — a body nginx's
`client_max_body_size` refused before Django saw it — to `upload_too_large`, the code the
backend's own limit answers with. Its text is here because the backups and files slices both
upload, and so are `empty` and `invalid_name`, the codes an uploaded file is refused with.
The files slice's codes (`file_exists`, `folder_not_empty`, `cannot_delete_root`,
`path_outside_roots`, `not_a_file`, `no_allowed_folders`) are here too, because `/activity`
lists failed `files.*` entries, and so is `permission_denied`, now that a page shows it.
The envfiles slice's `env_path_missing` and `env_too_large` are here for the same reason (`env.*`
entries). `password.*` holds the shared `PasswordPrompt`'s label and empty-field message, which the
servers host key review reads as well.

## Changing anything here

Every feature is downstream. `Identity`, `Page<T>` and `ApiError` are the
frontend half of the backend contract — change them and
`backend/apps/common/` or `backend/apps/accounts/` changes in the same slice.
