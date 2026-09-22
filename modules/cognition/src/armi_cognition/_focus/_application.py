"""Focus cognition application service."""

from armi_kernel.application import CandidateOwnerDraft

from ._codec import bind, decode
from .api import CandidateFocusDraft


class FocusApplication:
    def bind(self, value: CandidateFocusDraft) -> CandidateOwnerDraft:
        return bind(value)

    def decode(self, payload: bytes) -> CandidateFocusDraft:
        return decode(payload)


__all__ = ("FocusApplication",)
