"""Trusted per-transaction business time; authentication always uses wall time."""

from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from sqlite3 import Connection

BusinessClock = Callable[[], datetime]
_BINDING: ContextVar[tuple[tuple[Connection, BusinessClock], ...]] = ContextVar(
    "workflow_business_clock", default=()
)


def utc_now() -> datetime:
    return datetime.now(UTC)


def checked_time(clock: BusinessClock) -> datetime:
    value = clock()
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() != timedelta(0)
    ):
        raise ValueError("Business clock must return an aware UTC datetime")
    return value


@contextmanager
def bind_business_clock(tx: Connection, clock: BusinessClock):
    token = _BINDING.set((*_BINDING.get(), (tx, clock)))
    try:
        yield
    finally:
        _BINDING.reset(token)


def business_time(tx: Connection) -> datetime:
    for connection, clock in reversed(_BINDING.get()):
        if connection is tx:
            return checked_time(clock)
    return utc_now()
