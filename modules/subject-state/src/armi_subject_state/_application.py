"""Subject-state cognition application service."""

from armi_kernel.application import CandidateOwnerDraft

from ._codec import bind, decode
from .api import CandidateSubjectStateDraft


class SubjectStateApplication:
    def bind(self, value: CandidateSubjectStateDraft) -> CandidateOwnerDraft:
        return bind(value)

    def decode(self, payload: bytes) -> CandidateSubjectStateDraft:
        return decode(payload)


__all__ = ("SubjectStateApplication",)
