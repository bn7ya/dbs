"""Optional transports for shipping a backup off the box (SSH/SFTP)."""

from .ssh import SSHTarget, list_backups, pull_backup, push_backup

__all__ = ["SSHTarget", "push_backup", "pull_backup", "list_backups"]
