"""Explicit composition surface for isolated model verification tools."""

from armi_cognition.bootstrap import (
    AUTONOMOUS_ACTIVITY_INSTRUCTIONS,
    GENERIC_COGNITION_INSTRUCTIONS,
    CandidateOwner,
    autonomous_schema_for_context,
    bind_context_schema,
    load_purpose_binding,
    model_response_candidate,
)
from armi_cognition.bootstrap import (
    build_candidate_schema as candidate_schema,
)
from armi_cognition.bootstrap import (
    build_model_request_bytes as build_request_bytes,
)
from armi_cognition.bootstrap import (
    check_model_request as checked_model_request,
)
from armi_cognition.bootstrap import (
    compose_candidate_validation_context as CandidateValidationContext,
)
from armi_cognition.bootstrap import (
    load_active_model_binding as load_active_binding,
)
from armi_cognition.bootstrap import (
    parse_model_candidate as parse_candidate,
)

__all__ = (
    "AUTONOMOUS_ACTIVITY_INSTRUCTIONS",
    "GENERIC_COGNITION_INSTRUCTIONS",
    "CandidateOwner",
    "CandidateValidationContext",
    "autonomous_schema_for_context",
    "bind_context_schema",
    "build_request_bytes",
    "candidate_schema",
    "checked_model_request",
    "load_active_binding",
    "load_purpose_binding",
    "model_response_candidate",
    "parse_candidate",
)
