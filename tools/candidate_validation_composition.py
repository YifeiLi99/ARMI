"""Explicit owner codec composition for isolated candidate verification tools."""

from __future__ import annotations

from armi_activity.bootstrap import bootstrap_activity_cognition
from armi_cognition import CandidateValidationContext, DeterministicCandidateValidator
from armi_material.bootstrap import bootstrap_material_cognition
from armi_memory.bootstrap import bootstrap_memory_cognition
from armi_mood.bootstrap import bootstrap_mood_cognition
from armi_prompt.bootstrap import bootstrap_prompt_cognition
from armi_relationship.bootstrap import bootstrap_relationship_cognition
from armi_sleep.bootstrap import bootstrap_sleep_cognition
from armi_subject_state.bootstrap import bootstrap_subject_state_cognition


def build_candidate_validator(
    context: CandidateValidationContext,
) -> DeterministicCandidateValidator:
    """Compose the validator without relying on hidden constructor defaults."""
    return DeterministicCandidateValidator(
        context,
        activity_cognition=bootstrap_activity_cognition(),
        material_cognition=bootstrap_material_cognition(),
        memory_cognition=bootstrap_memory_cognition(),
        mood_cognition=bootstrap_mood_cognition(),
        prompt_cognition=bootstrap_prompt_cognition(),
        relationship_cognition=bootstrap_relationship_cognition(),
        sleep_cognition=bootstrap_sleep_cognition(),
        subject_state_cognition=bootstrap_subject_state_cognition(),
    )
