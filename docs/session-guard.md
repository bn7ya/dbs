# The session guard

The panel can export and overwrite your whole database, so DBS watches every admin request
from a superuser and acts when a session looks wrong.

## How it decides

Each request is scored on the time of day, the request rate, how risky the action is, the
session's age, failed sign-ins, and whether the network and browser are familiar. The score
comes from rules and from an `IsolationForest` that ships pre-trained and is refitted in the
background on the account's own history. Changes to users, groups, permissions and passwords
count as high-risk actions.

- **A warning flags the session.** A flagged session can still read, but every change anywhere
  in the admin, and every download or export, is refused and ends the session; it must sign in
  again.
- **A high enough score ends that account's sessions.**
- **Learning never switches enforcement off.** During an account's first sessions the model is
  muted, because everything about a new account looks unusual, but the rules and both
  thresholds still apply. A per-account model is fitted once there are `DBS_ANOMALY_MIN_ROWS`
  events (50 by default).
- **Idle sessions end.** A session idle in the admin for longer than the level's idle timeout
  is ended on its next request.

| Level | Idle timeout |
|---|---|
| Relaxed | 8 hours |
| Balanced (the default) | 2 hours |
| Strict | 30 minutes |
| Paranoid | 15 minutes |

The wizard on your first visit to `/admin/dbs/` sets the level and the networks you sign in
from; **Security** changes them later. An idle timeout of 0 turns it off.

## If it locks you out

A shell always wins:

```bash
python manage.py dbs security unlock alice
```

Then add your network to the trusted list. `dbs security` also takes `status` (the idle
timeout and whether the anomaly model can run), `policy`, `retrain`, `reset-baseline USER`,
`events` and `purge`.

## Tuning it

| Setting | Default | |
|---|---|---|
| `DBS_TRUSTED_NETWORKS` | none | CIDRs that are scored but never enforced against |
| `DBS_ANOMALY_ENFORCE` | `True` | `False` never ends a session; the highest a score reaches is a flag |
| `DBS_GEOLOCATION` | `False` | Adds the browser's location as a signal; it can only ever raise a score |
| `DBS_GUARD_POLL_SECONDS` | `15` | How often an open page asks whether its session is still allowed |
| `DBS_GUARD_EVERYWHERE` | `False` | Extends that check to every admin page, not only the panel's |
| `DBS_SETUP_WIZARD` | `True` | Sends superusers to the wizard until it is configured |
| `DBS_ANOMALY_DETECTOR` | the built-in one | A dotted path to a replacement detector class |
| `DBS_SECURITY_RETENTION_DAYS` | `90` | How long telemetry is kept before it is purged, once a day |

Trusted networks and proxies may be no wider than /8 (IPv4) or /16 (IPv6); wider entries are
refused by the form and ignored when read, so a session can never trust the whole internet.

## Behind a reverse proxy

Set `DBS_TRUST_FORWARDED_FOR = True` and list the proxies' networks in `DBS_TRUSTED_PROXIES`,
for example `["10.0.0.0/24"]`. `X-Forwarded-For` is read only from a request that arrives from
one of them, walking the header from the right to the first address that is not a proxy. An
address the guard cannot read counts as a new network, never a trusted one.

## What it keeps

Session events store the /24 (IPv4) or /48 (IPv6) network and a keyed hash of the full address;
anomalies store only the network. Telemetry older than `DBS_SECURITY_RETENTION_DAYS` is removed
once a day. The audit trail is never purged with it.

## Checks

The forest needs scikit-learn, which `pip install django-dbs` installs. If it cannot be
imported, the guard scores with its rules alone. `manage.py check` warns about the ways a guard
can be set up wrong:

| Check | Means |
|---|---|
| `dbs.security.W001` | `DBS_TRUST_FORWARDED_FOR` is on, but `DBS_TRUSTED_PROXIES` names no proxy network |
| `dbs.security.W002` | `DBSSecurityMiddleware` runs before `AuthenticationMiddleware`, so it scores nothing |
| `dbs.security.W003` | scikit-learn cannot be imported; `pip install --force-reinstall "django-dbs"` repairs it |
