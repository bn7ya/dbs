"""Backup configuration for the test app (auto-discovered like admin.py)."""

from dbs import FieldType, ModelBackup, backup_registry

from .models import Author, Book, Tag

backup_registry.register(Author)
backup_registry.register(Tag)


@backup_registry.register(Book)
class BookBackup(ModelBackup):
    overrides = {
        # cover is auto-detected as FILE; sidecar_path is a CharField we map by hand.
        "sidecar_path": FieldType.FILE_PATH,
    }
