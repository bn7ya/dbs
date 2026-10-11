from __future__ import annotations

import os
import socket


def pid_running(pid: int) -> bool:
    if os.name != "posix":
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def abandoned(owner: str) -> bool:
    host, _, pid = owner.rpartition(":")
    if host != socket.gethostname() or not pid.isdigit():
        return False
    return int(pid) != os.getpid() and not pid_running(int(pid))
