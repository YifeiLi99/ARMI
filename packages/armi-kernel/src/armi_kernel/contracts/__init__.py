"""The only public cross-distribution transport contract entry point."""

from ._codec import CONTRACT_VERSION, ContractViolation
from .errors import ErrorCategory, ErrorDescriptor
from .ids import (
    ErrorInstanceId,
    ResultRef,
    SceneId,
    SubjectId,
    TraceId,
)
from .outcomes import (
    AcceptedOutcome,
    AppliedOutcome,
    CompletedOutcome,
    FailedOutcome,
    Outcome,
    RejectedOutcome,
    UnavailableOutcome,
    UnknownOutcome,
    WaitingOutcome,
)
from .pagination import Page, PageRequest
from .values import Digest, IdempotencyKey, Instant, OpaqueCursor, Purpose

__all__ = (
    "CONTRACT_VERSION",
    "AcceptedOutcome",
    "AppliedOutcome",
    "CompletedOutcome",
    "ContractViolation",
    "Digest",
    "ErrorCategory",
    "ErrorDescriptor",
    "ErrorInstanceId",
    "FailedOutcome",
    "IdempotencyKey",
    "Instant",
    "OpaqueCursor",
    "Outcome",
    "Page",
    "PageRequest",
    "Purpose",
    "RejectedOutcome",
    "ResultRef",
    "SceneId",
    "SubjectId",
    "TraceId",
    "UnavailableOutcome",
    "UnknownOutcome",
    "WaitingOutcome",
)
