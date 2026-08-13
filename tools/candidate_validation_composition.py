"""Explicit owner codec composition for isolated candidate verification tools."""

from __future__ import annotations

from armi_activity.api import default_activity_cognition
from armi_cognition import CandidateValidationContext, DeterministicCandidateValidator
from armi_material.api import default_material_cognition
from armi_memory.api import default_memory_cognition
from armi_mood.api import default_mood_cognition
from armi_prompt.api import default_prompt_cognition
from armi_relationship.bootstrap import bootstrap_relationship_cognition
from armi_sleep.api import default_sleep_cognition
from armi_subject_state.api import default_subject_state_cognition


def build_candidate_validator(
    context: CandidateValidationContext,
) -> DeterministicCandidateValidator:
    """Compose the validator without relying on hidden constructor defaults."""
    return DeterministicCandidateValidator(
        context,
        activity_cognition=default_activity_cognition(),
        material_cognition=default_material_cognition(),
        memory_cognition=default_memory_cognition(),
        mood_cognition=default_mood_cognition(),
        prompt_cognition=default_prompt_cognition(),
        relationship_cognition=bootstrap_relationship_cognition(),
        sleep_cognition=default_sleep_cognition(),
        subject_state_cognition=default_subject_state_cognition(),
    )
