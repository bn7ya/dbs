from dbs import backup_registry

from .models import Note

backup_registry.register(Note)
