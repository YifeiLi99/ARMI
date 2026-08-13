"""Cognition-private fixed candidate owner vocabulary."""

from enum import StrEnum


class CandidateOwner(StrEnum):
    EXPERIENCE = "experience"
    SELF = "self"
    MIND = "mind"
    MOOD = "mood"
    LIFE_MODE = "life_mode"
    MEMORY = "memory"
    RELATIONSHIP = "relationship"
    ACTIVITY = "activity"
    CAPABILITY = "capability"
    ACTION = "action"
    WEB_RESEARCH = "web_research"
    CODEX_DELEGATION = "codex_delegation"
    SLEEP = "sleep"
    MATERIAL = "material"
    PROMPT = "prompt"
    EXACT_LIFE_QUERY = "exact_life_query"


__all__ = ("CandidateOwner",)
