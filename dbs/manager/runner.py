from __future__ import annotations

import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor

from django.db import close_old_connections, connection

from .conf import jobs_inline

logger = logging.getLogger("dbs.manager")

WORKERS = 4


def _run_job(function, args, kwargs):
    close_old_connections()
    try:
        return function(*args, **kwargs)
    except BaseException:
        logger.exception("job %s failed", getattr(function, "__qualname__", function))
        raise
    finally:
        connection.close()


def _run_inline(function, args, kwargs):
    future = Future()
    future.set_result(function(*args, **kwargs))
    return future


class JobRunner:
    def __init__(self, workers=WORKERS):
        self.workers = workers
        self._executor = None
        self._lock = threading.Lock()

    def start(self):
        with self._lock:
            if self._executor is None:
                self._executor = ThreadPoolExecutor(
                    max_workers=self.workers, thread_name_prefix="dbs-manager-job"
                )
        return self

    def submit(self, function, *args, **kwargs):
        if jobs_inline():
            return _run_inline(function, args, kwargs)
        self.start()
        return self._executor.submit(_run_job, function, args, kwargs)

    def shutdown(self, wait=True):
        with self._lock:
            executor, self._executor = self._executor, None
        if executor is not None:
            executor.shutdown(wait=wait)

    @property
    def running(self):
        return self._executor is not None


_runner = JobRunner()


def get_runner():
    return _runner
