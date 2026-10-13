# The DBS session guard

The `/admin/dbs/` panel can download and overwrite the whole database, so it is superuser
only and every admin request is scored.

## Features

Time of day, seconds since the previous event, request rate, the risk weight of the
attempted action, session age, whether the IP prefix (/24 or /48) and user agent are new for
that account, distinct prefixes today, and — when `DBS_GEOLOCATION = True` — distance from a
known location and implied travel speed. Changes to users, groups, permissions and passwords
in the Django admin are high-risk actions.

## The model

`sklearn.ensemble.IsolationForest`, installed by `pip install "django-dbs[guard]"`. A base
model ships pre-trained on a synthetic corpus (`dbs/security/baseline.json.gz`, regenerated
by `scripts/train_base_model.py`) so scoring works from the first request. Once an account
has `DBS_ANOMALY_MIN_ROWS` events, a personal forest is fitted on its newest 2000 rows mixed
with a shrinking sample of that corpus, in a background thread, at most every 15 minutes or
200 requests; a request never waits for it. Without scikit-learn the guard scores with its
rules alone, and `manage.py check` warns (`dbs.security.W003`).

**Nothing is ever pickled or unpickled.** Models are refit from stored feature rows. Do not
"optimise" this by persisting a fitted estimator — that would be a deserialization hole in
the security layer.

## Rules on top of the model

A new network prefix, a new browser, implied travel above 900 km/h, and a destructive action
from an unrecognised network each add risk. An address the guard cannot read counts as a new
network. Client-supplied signals — location above all — may only ever **add** risk, never
subtract it, because they can be forged. Preserve that property in any change.

## Outcomes

`warn` records an `AnomalyEvent` and flags the session: it can still read, but every
change anywhere in the admin, and every download or export, is refused until it signs in
again. `block` records one, creates a `Lockout`, ends every session for that account and
optionally emails. Requests from `DBS_TRUSTED_NETWORKS` are scored and recorded but never
enforced against. During an account's learning period only the model is muted; the rules
and both thresholds still apply.

A session idle in the admin for longer than the policy's idle timeout (480, 120, 30 or 15
minutes by level; 0 turns it off) is ended on its next request.

Recovery is always available from a shell: `python manage.py dbs security unlock USER`.

## Behind a proxy

`X-Forwarded-For` is read only when `DBS_TRUST_FORWARDED_FOR = True` and the request comes
from a network listed in `DBS_TRUSTED_PROXIES` (CIDRs, e.g. `["10.0.0.0/24"]`), walking the
header from the right to the first address that is not a proxy. `manage.py check` warns
(`dbs.security.W001`) when the header is trusted with no proxy listed, and `W002` when
`DBSSecurityMiddleware` sits above `AuthenticationMiddleware`.

## Telemetry

Session events keep the /24 or /48 network and an HMAC of the full address keyed to
`SECRET_KEY`; anomalies keep only the network. Telemetry older than
`DBS_SECURITY_RETENTION_DAYS` (90) is purged automatically once a day; `dbs security purge`
does the same on demand. Neither touches the audit trail.

## Invariants to preserve

- A session never establishes its own familiarity: "seen" prefixes and browsers come only
  from *other* sessions, so an attacker cannot clear the new-network signal by making one
  extra request.
- A `warn` verdict is enforced, not cosmetic: the middleware refuses any change, download or
  export from a flagged session until it signs in again.
- Learning never switches enforcement off.
- A lockout is checked on every authenticated superuser request, not only inside the panel,
  so it applies whatever the session backend.
- `BackupRecord.location` is read-only and `download` serves only a file resolved inside
  `DBS_BACKUP_DIR`. It is a backup catalogue, not a file browser.
- The panel runs no remote command and stores no SSH credential.
- Trusted networks and proxies no wider than /8 (v4) or /16 (v6) — a guarded session
  must not be able to trust the whole internet.
