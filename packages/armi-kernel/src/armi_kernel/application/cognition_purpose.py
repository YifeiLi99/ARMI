"""Closed cognition-purpose registry shared by opportunity and cognition owners."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Literal


class CognitionPurpose(StrEnum):
    CONSIDER_CREATOR_INPUT = "consider_creator_input"
    CONSIDER_CREATOR_VOICE_INPUT = "consider_creator_voice_input"
    CONSIDER_WEB_EVIDENCE = "consider_web_evidence"
    CONSIDER_CODEX_TASK = "consider_codex_task"
    CONSIDER_CODEX_RESULT = "consider_codex_result"
    CONSIDER_AUTONOMOUS_LIFE = "consider_autonomous_life"
    CONSIDER_ACTIVITY_ATTENTION = "consider_activity_attention"
    CONSIDER_ACTIVITY_INTERNAL_WORK = "consider_activity_internal_work"
    CONSIDER_SLEEP = "consider_sleep"
    CONSIDER_LIFE_QUERY_RESULT = "consider_life_query_result"
    MAINTAIN_SUBJECTIVE_MEMORY = "maintain_subjective_memory"
    PERFORM_SUBJECT_SELF_CHECK = "perform_subject_self_check"
    CONSIDER_CREATOR_OUTREACH = "consider_creator_outreach"
    CONSIDER_OTHER_HUMAN_INPUT = "consider_other_human_input"
    CONSIDER_VISUAL_OBSERVATION = "consider_visual_observation"
    REFLECT_SELF = "reflect_self"
    REFLECT_MIND = "reflect_mind"
    REFLECT_MOOD = "reflect_mood"
    REFLECT_PROMPT = "reflect_prompt"


@dataclass(frozen=True, slots=True)
class CognitionPurposeDefinition:
    scene_requirement: Literal["required", "forbidden"]
    context_profile: str
    candidate_family: str


_SCENELESS = frozenset(
    {
        CognitionPurpose.CONSIDER_AUTONOMOUS_LIFE,
        CognitionPurpose.CONSIDER_ACTIVITY_ATTENTION,
        CognitionPurpose.CONSIDER_ACTIVITY_INTERNAL_WORK,
        CognitionPurpose.CONSIDER_SLEEP,
        CognitionPurpose.MAINTAIN_SUBJECTIVE_MEMORY,
        CognitionPurpose.PERFORM_SUBJECT_SELF_CHECK,
        CognitionPurpose.CONSIDER_VISUAL_OBSERVATION,
        CognitionPurpose.REFLECT_SELF,
        CognitionPurpose.REFLECT_MIND,
        CognitionPurpose.REFLECT_MOOD,
        CognitionPurpose.REFLECT_PROMPT,
    }
)

COGNITION_PURPOSES: Final = MappingProxyType(
    {
        purpose: CognitionPurposeDefinition(
            "forbidden" if purpose in _SCENELESS else "required",
            purpose.value,
            (
                "owner_reflection"
                if purpose.value.startswith("reflect_")
                else "creator_dialogue"
                if purpose
                in {
                    CognitionPurpose.CONSIDER_CREATOR_INPUT,
                    CognitionPurpose.CONSIDER_CREATOR_VOICE_INPUT,
                    CognitionPurpose.CONSIDER_LIFE_QUERY_RESULT,
                }
                else "single_candidate"
            ),
        )
        for purpose in CognitionPurpose
    }
)


def require_cognition_purpose(value: str) -> CognitionPurpose:
    try:
        return CognitionPurpose(value)
    except ValueError:
        raise ValueError("CANDIDATE-PURPOSE") from None


__all__ = (
    "COGNITION_PURPOSES",
    "CognitionPurpose",
    "CognitionPurposeDefinition",
    "require_cognition_purpose",
)
