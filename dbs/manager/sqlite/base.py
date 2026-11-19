from __future__ import annotations

from django.core.exceptions import ImproperlyConfigured
from django.db.backends.sqlite3 import base

TRANSACTION_MODES = frozenset({"DEFERRED", "EXCLUSIVE", "IMMEDIATE"})


class DatabaseWrapper(base.DatabaseWrapper):
    transaction_mode = None

    def get_connection_params(self):
        params = super().get_connection_params()
        mode = params.pop("transaction_mode", self.transaction_mode)
        if mode is not None and mode.upper() not in TRANSACTION_MODES:
            raise ImproperlyConfigured(
                f"settings.DATABASES[{self.alias!r}]['OPTIONS']['transaction_mode'] is "
                f"{mode!r}; use one of {', '.join(sorted(TRANSACTION_MODES))}, or None."
            )
        self.transaction_mode = mode
        return params

    def _start_transaction_under_autocommit(self):
        if self.transaction_mode is None:
            self.cursor().execute("BEGIN")
        else:
            self.cursor().execute(f"BEGIN {self.transaction_mode}")
