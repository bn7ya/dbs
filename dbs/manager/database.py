from __future__ import annotations

from urllib.parse import parse_qsl, unquote, urlsplit

SQLITE_TIMEOUT = 30
ENGINES = {
    "sqlite": "django.db.backends.sqlite3",
    "sqlite3": "django.db.backends.sqlite3",
    "postgres": "django.db.backends.postgresql",
    "postgresql": "django.db.backends.postgresql",
    "pgsql": "django.db.backends.postgresql",
    "mysql": "django.db.backends.mysql",
}
DEFAULT_PORTS = {
    "django.db.backends.postgresql": 5432,
    "django.db.backends.mysql": 3306,
}


class DatabaseURLError(ValueError):
    pass


def sqlite_database(path):
    return {
        "ENGINE": ENGINES["sqlite"],
        "NAME": str(path),
        "OPTIONS": {"timeout": SQLITE_TIMEOUT},
    }


def parse_database_url(url):
    parts = urlsplit(url)
    scheme = parts.scheme.lower().split("+", 1)[0]
    engine = ENGINES.get(scheme)
    if engine is None:
        raise DatabaseURLError(
            f"Use a sqlite://, postgres:// or mysql:// URL, not {parts.scheme or url!r}."
        )
    if engine == ENGINES["sqlite"]:
        return _sqlite(url, parts)
    name = unquote(parts.path.lstrip("/"))
    if not name:
        raise DatabaseURLError("Name the database at the end of the URL.")
    options = dict(parse_qsl(parts.query))
    return {
        "ENGINE": engine,
        "NAME": name,
        "USER": unquote(parts.username or ""),
        "PASSWORD": unquote(parts.password or ""),
        "HOST": parts.hostname or "",
        "PORT": str(parts.port or DEFAULT_PORTS[engine]),
        "OPTIONS": options,
    }


def _sqlite(url, parts):
    remainder = url.split("://", 1)[1] if "://" in url else ""
    if remainder in ("", ":memory:", "/:memory:"):
        path = ":memory:"
    else:
        path = unquote(parts.path)[1:]
        if parts.netloc and parts.netloc not in ("", "localhost"):
            path = unquote(parts.netloc) + "/" + path
        if not path:
            raise DatabaseURLError("Give the SQLite file's path after sqlite:///.")
    database = sqlite_database(path)
    database["OPTIONS"].update(dict(parse_qsl(parts.query)))
    if "timeout" in database["OPTIONS"]:
        database["OPTIONS"]["timeout"] = float(database["OPTIONS"]["timeout"])
    return database
