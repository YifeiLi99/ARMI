"""Prompt candidate application service."""

from armi_kernel.application import CandidateOwnerDraft

from . import _codec
from .api import CandidatePromptDraft


class PromptApplication:
    __slots__ = ()

    def bind(self, value: CandidatePromptDraft) -> CandidateOwnerDraft:
        return _codec.bind(value)

    def decode(self, payload: bytes) -> CandidatePromptDraft:
        return _codec.decode(payload)

    def decode_legacy(self, value: object) -> CandidatePromptDraft:
        return _codec.decode_legacy(value)


__all__ = ("PromptApplication",)
