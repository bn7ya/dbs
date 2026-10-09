from __future__ import annotations


class Action:
    TAKE = "backup.take"
    VERIFY = "backup.verify"
    RESTORE = "backup.restore"
    DOWNLOAD = "backup.download"
    UPLOAD = "backup.upload"
    DELETE = "backup.delete"
    UNDO_DELETE = "backup.undo_delete"
    RUN = "backup.run"
    RETENTION = "backup.retention"
    EXPIRE = "backup.expire"
    PLAN_CREATE = "plan.create"
    PLAN_UPDATE = "plan.update"
    PLAN_DELETE = "plan.delete"
