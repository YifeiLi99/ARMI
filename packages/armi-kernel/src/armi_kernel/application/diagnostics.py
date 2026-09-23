"""Diagnostic context is observational: it never supplies business authority."""

from __future__ import annotations

import logging
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar

_CONTEXT: ContextVar[dict[str, str] | None] = ContextVar(
    "armi_diagnostic_context", default=None
)
CORRELATION_FIELDS = frozenset(
    {
        "trace_id",
        "request_id",
        "operation_id",
        "opportunity_id",
        "episode_id",
        "work_id",
        "attempt_id",
        "call_id",
        "effect_id",
        "session_id",
        "turn_id",
        "subject_commit_id",
        "interaction_id",
        "artifact_id",
    }
)


def diagnostic_context() -> dict[str, str]:
    return dict(_CONTEXT.get() or {})


@contextmanager
def diagnostic_scope(**identities: object) -> Generator[None]:
    unknown = identities.keys() - CORRELATION_FIELDS
    if unknown:
        raise ValueError(f"Unknown diagnostic identity: {sorted(unknown)}")
    token = _CONTEXT.set(
        {
            **(_CONTEXT.get() or {}),
            **{
                key: str(value)
                for key, value in identities.items()
                if value is not None
            },
        }
    )
    try:
        yield
    finally:
        _CONTEXT.reset(token)


def record_diagnostic(
    event: str,
    *,
    component: str,
    level: int = logging.INFO,
    message: str | None = None,
    error: BaseException | None = None,
    **details: object,
) -> None:
    """Log through the process sink, including the original exception if present."""
    logging.getLogger("armi." + component).log(
        level,
        message or event,
        extra={
            "armi_event": event,
            "armi_details": details,
            "diagnostic_context": diagnostic_context(),
        },
        exc_info=None if error is None else (type(error), error, error.__traceback__),
        stacklevel=2,
    )


__all__ = (
    "CORRELATION_FIELDS",
    "diagnostic_context",
    "diagnostic_scope",
    "record_diagnostic",
)
