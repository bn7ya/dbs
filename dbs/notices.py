from __future__ import annotations

from dataclasses import dataclass

MODELS_LEFT_OUT = "models_left_out"
FIELDS_LEFT_OUT = "fields_left_out"
FIELDS_NOT_IN_BACKUP = "fields_not_in_backup"
FILES_LEFT_OUT = "files_left_out"
MERGED = "merged"
MIGRATIONS_DIFFER = "migrations_differ"
DJANGO_VERSION = "django_version"
REFERENCES_LEFT_OUT = "references_left_out"
REFERENCES_BY_ID = "references_by_id"


@dataclass(frozen=True)
class RestoreWarning:
    code: str
    message: str

    def __str__(self) -> str:
        return self.message
