"""Isolated composition for paid/offline candidate verification tools."""

from typing import Any, cast

from armi_activity.bootstrap import bootstrap_activity_cognition
from armi_cognition.api import CandidateValidator
from armi_cognition.bootstrap import bootstrap_cognition_validator
from armi_material.bootstrap import bootstrap_material_cognition
from armi_memory.bootstrap import bootstrap_memory_cognition
from armi_mood.bootstrap import bootstrap_mood_cognition
from armi_prompt.bootstrap import bootstrap_prompt_cognition
from armi_relationship.bootstrap import bootstrap_relationship_cognition
from armi_sleep.bootstrap import bootstrap_sleep_cognition
from armi_subject_state.bootstrap import bootstrap_subject_state_cognition


def build_candidate_validator(context: object) -> CandidateValidator:
    return bootstrap_cognition_validator(
        cast(Any, context),
        activity=bootstrap_activity_cognition(),
        material=bootstrap_material_cognition(),
        memory=bootstrap_memory_cognition(),
        mood=bootstrap_mood_cognition(),
        prompt=bootstrap_prompt_cognition(),
        relationship=bootstrap_relationship_cognition(),
        sleep=bootstrap_sleep_cognition(),
        subject_state=bootstrap_subject_state_cognition(),
    )


__all__ = (
    "bootstrap_activity_cognition",
    "bootstrap_material_cognition",
    "bootstrap_memory_cognition",
    "bootstrap_mood_cognition",
    "bootstrap_prompt_cognition",
    "bootstrap_relationship_cognition",
    "bootstrap_sleep_cognition",
    "bootstrap_subject_state_cognition",
    "build_candidate_validator",
)
