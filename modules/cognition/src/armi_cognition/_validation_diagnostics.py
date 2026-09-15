"""Safe structured failures; model text is kept only in response artifacts."""

from __future__ import annotations

import json
from uuid import uuid7

from armi_kernel.application import CandidateValidationId
from pydantic import ValidationError

from .api import (
    CandidateDiagnostic,
    CandidateValidationResult,
    CandidateValidationStatus,
)


def contract_rejection(error: BaseException) -> CandidateValidationResult:
    cause = error
    while cause.__cause__ is not None:
        cause = cause.__cause__
    if isinstance(cause, ValidationError):
        diagnostics = tuple(
            CandidateDiagnostic(
                "structure", item["type"], tuple(item["loc"]), "cognition"
            )
            for item in cause.errors(
                include_url=False, include_context=False, include_input=False
            )
        )
    elif isinstance(cause, (json.JSONDecodeError, UnicodeError)):
        diagnostics = (CandidateDiagnostic("parse", "CANDIDATE-JSON", (), "cognition"),)
    else:
        diagnostics = (
            CandidateDiagnostic("structure", "CANDIDATE-CONTRACT", (), "cognition"),
        )
    return CandidateValidationResult(
        CandidateValidationId(uuid7()),
        CandidateValidationStatus.REJECTED,
        None,
        0,
        0,
        "CANDIDATE-CONTRACT",
        diagnostics,
    )
