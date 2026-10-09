# shared

Components, pipes and directives used by **more than one** feature.

The bar is two callers. Used by one feature — it belongs in that feature. Needed
by every feature to function at all — it belongs in `core/`. Moving something
here early is how a shared directory fills with things nobody shares.

`shared/` must never import from `@features/*`. That dependency runs the wrong
way and turns a shared component into a feature's private one.

## What lives here

| Component | Used by |
|---|---|
| `status-page/` | `/forbidden`, `/**` — any full-page dead end with one way out |
| `money/` | Every amount of money, in every feature (rule 29) |
| `field/` | Every form control's label, hint and error |
| `toaster/`, `confirm/`, `dialogs/` | Every feature that reports, asks or collects in a dialog |
| `empty-state/` | Every list or table that can have nothing in it |
| `app-date/` | Every date and time a table or card shows |
| `file-size/` | `fileSize` pipe — the backups and files tables |
| `password-prompt/` | The reader's password before showing a backup passphrase (servers), showing or pushing a `.env` version (envfiles) |

`StatusPage` takes `titleKey` and `bodyKey` as translation keys, bound straight
from route `data` by `withComponentInputBinding()`. A new status page is a route
entry and two translation keys, not another component.

A feature never injects PrimeNG's `MessageService`, `ConfirmationService` or `DialogService`: it
uses `Toaster`, `Confirmation` and `Dialogs`, which keep one look and one set of translated
defaults. A page that opens dialogs lists `providers: [Dialogs]`, so the dialog
resolves the page's own route-level providers. `<p-toast>` and `<p-confirmdialog>` live once, in
`App`.

`<app-field>` frames every control (see its entry below). A native `pInputText` or `pTextarea`
inside it takes `appFieldControl`; a PrimeNG component with its input inside (`p-select`,
`p-inputnumber`, `p-password`) takes `[inputId]="field.id"` from the field's `exportAs`.

## Classes and methods

**`StatusPage`** — a full-page message with one way back to the start; the title and body
are translation keys from the route's `data`.

**`Money`** (`<app-money [amount]>`) — an amount in Omani rials: three decimals, Latin
digits in both languages, the rial sign beside it and the currency's name for screen
readers. `RIAL_SIGN` is U+20C4.

**`Field`** (`<app-field>`) — the frame around one control: label, optional hint, optional error.
Inputs `label`, `hint`, `error`, `required`. Exposes `id`, `invalid` and `describedBy`.

**`FieldControl`** (`appFieldControl`) — applies the field's `id`, `aria-describedby` and
`aria-invalid` to a native control inside it.

**`Toaster`** — `add({ severity, summary })` shows a toast. Severities: `success`, `info`,
`warning`, `danger`. The summary is already translated.

**`Confirmation`** — `ask(options)` shows a confirm dialog and resolves `true` on accept, `false`
on reject or dismiss.

**`Dialogs`** — `open<R, D>(Component, { titleKey, data, size })` opens a component in a modal (`size`: `sm`, `md` or `lg`) and
returns `{ closed, whenClosed() }`; the result is `undefined` when the reader dismissed it.
`injectDialogData<D>()` and `injectDialogRef<R>()` are what the dialog component injects.

**`EmptyState`** (`<app-empty-state>`) — a centred icon, title and description, with its call to
action projected inside. Inputs `icon` (a Font Awesome class string), `title`, `description`,
`headingLevel` (1, 2 or 3; 1 for a full-page state).

**`AppDatePipe`** (`appDate`) — a date and time in the reader's language: Gregorian, Latin digits.
Impure for the same reason as `t`: the value does not change when the language does.

**`FileSizePipe`** (`fileSize`) — bytes as a reader says them, in decimal steps and the reader's
language. Impure for the same reason as `t`.

**`PasswordPrompt`** — a dialog that asks for the reader's password and runs the operation it
guards (`PasswordPromptData.submit`). It shows `invalid_password` under the field and any other
failure above it, so a wrong password is retried in place, and closes with `true` once the
operation succeeded.

**`uniqueId(prefix)`** — a page-unique id for wiring a label to a control.

## Conventions

Same rules as a feature component: standalone, `OnPush`, three files, PrimeNG for every
interactive element, tokens as `var(--app-*)`, no raw px.

Strings that a shared component renders live in `core/i18n/{en,ar}.json`, since
there is no one feature bundle to put them in.

`unifier` audits this directory: when the same fix appears in three features, it
belongs here instead.
