"""Business time; transport timeouts and provider metering keep real time."""

from collections.abc import Callable
from contextvars import ContextVar, Token
from datetime import UTC, datetime, timedelta

_OFFSET: ContextVar[Callable[[], int] | None] = ContextVar(
    "business_time", default=None
)


def business_offset_microseconds() -> int:
    read = _OFFSET.get()
    return 0 if read is None else read()


def business_clock_injected() -> bool:
    return _OFFSET.get() is not None


def business_now() -> datetime:
    return datetime.now(UTC) + timedelta(microseconds=business_offset_microseconds())


def bind_business_clock(read: Callable[[], int]) -> Token[Callable[[], int] | None]:
    return _OFFSET.set(read)


def reset_business_clock(token: Token[Callable[[], int] | None]) -> None:
    _OFFSET.reset(token)
