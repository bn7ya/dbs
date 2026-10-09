from __future__ import annotations

from django.db import models


class RestoreMode(models.TextChoices):
    MERGE = "merge"
    REPLACE = "replace"
