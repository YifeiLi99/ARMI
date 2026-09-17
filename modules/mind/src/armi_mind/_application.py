"""Mind cognition application service."""

from armi_kernel.application import CandidateOwnerDraft

from ._codec import bind, decode
from .api import CandidateMindDraft


class MindApplication:
    def bind(self, value: CandidateMindDraft) -> CandidateOwnerDraft:
        return bind(value)

    def decode(self, payload: bytes) -> CandidateMindDraft:
        return decode(payload)


__all__ = ("MindApplication",)
