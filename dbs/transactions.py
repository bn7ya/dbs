from __future__ import annotations

import functools
from contextlib import ExitStack, contextmanager

from django.db import connections, router, transaction


def own_database():
    from .models import AuditEvent

    return router.db_for_write(AuditEvent)


def databases_of(*models):
    return [router.db_for_write(model) for model in models]


@contextmanager
def atomic_on(*aliases):
    with ExitStack() as stack:
        for alias in dict.fromkeys(aliases):
            stack.enter_context(transaction.atomic(using=alias))
        yield


@contextmanager
def reading_on(*aliases):
    with ExitStack() as stack:
        for alias in dict.fromkeys(aliases):
            with _beginning_without_the_write_lock(connections[alias]):
                stack.enter_context(transaction.atomic(using=alias))
        yield


@contextmanager
def _beginning_without_the_write_lock(connection):
    connection.ensure_connection()
    mode = getattr(connection, "transaction_mode", None)
    if mode is None:
        yield
        return
    connection.transaction_mode = None
    try:
        yield
    finally:
        connection.transaction_mode = mode


def atomic():
    return atomic_on(own_database())


def reading():
    return reading_on(own_database())


def atomic_for(*models):
    return atomic_on(*databases_of(*models))


def reading_for(*models):
    return reading_on(*databases_of(*models))


def _inside(block):
    def decorate(function):
        @functools.wraps(function)
        def run(*args, **kwargs):
            with block():
                return function(*args, **kwargs)

        return run

    return decorate


def _inside_on_connection(block):
    def decorate(function):
        @functools.wraps(function)
        def run(connection, *args, **kwargs):
            with block(connection.alias):
                return function(connection, *args, **kwargs)

        return run

    return decorate


atomically = _inside(atomic)
reads = _inside(reading)
atomically_on_connection = _inside_on_connection(atomic_on)
reads_connection = _inside_on_connection(reading_on)
