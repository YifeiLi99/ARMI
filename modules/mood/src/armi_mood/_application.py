"""Mood cognition application service."""

from armi_kernel.application import CandidateOwnerDraft

from ._codec import bind, decode
from .api import CandidateMoodDraft


class MoodApplication:
    def bind(self, value: CandidateMoodDraft) -> CandidateOwnerDraft:
        return bind(value)

    def decode(self, payload: bytes) -> CandidateMoodDraft:
        return decode(payload)


__all__ = ("MoodApplication",)
