"""ARMI cognition module public surface."""

from ._change_set_codec import parse_subject_change_set
from ._model_contract import (
    build_request_bytes,
    candidate_schema,
    checked_model_request,
    load_active_binding,
    parse_candidate,
)
from ._validator import CandidateValidationContext, DeterministicCandidateValidator
from .api import (
    CandidateValidationResult,
    CandidateValidationStatus,
    CandidateValidator,
    CognitionArtifactCatalogPort,
    CognitionCandidateParser,
    CognitionCandidateValue,
    CognitionModelAdapterFactory,
    CognitionModelPort,
    CognitionWakeupPort,
    CognitionWorkerPort,
    SubjectChangeSet,
)

__all__ = (
    "CandidateValidationContext",
    "CandidateValidationResult",
    "CandidateValidationStatus",
    "CandidateValidator",
    "CognitionArtifactCatalogPort",
    "CognitionCandidateParser",
    "CognitionCandidateValue",
    "CognitionModelAdapterFactory",
    "CognitionModelPort",
    "CognitionWakeupPort",
    "CognitionWorkerPort",
    "DeterministicCandidateValidator",
    "SubjectChangeSet",
    "build_request_bytes",
    "candidate_schema",
    "checked_model_request",
    "load_active_binding",
    "parse_candidate",
    "parse_subject_change_set",
)
