"""Activity candidate binding application service."""

from __future__ import annotations

from armi_kernel.application import CandidateFactClass, CandidateOwnerDraft

from ._codec import decode, decode_legacy, encode
from .api import CandidateActivityDecisionDraft, CandidateActivityDraft


class ActivityApplication:
    __slots__ = ()

    def bind_create(self, value: CandidateActivityDraft) -> CandidateOwnerDraft:
        return CandidateOwnerDraft(
            value.proposal_ref,
            value.atomic_group_ref,
            value.basis_ordinals,
            value.fact_class,
            "activity",
            encode(value),
        )

    def bind_decision(
        self, value: CandidateActivityDecisionDraft
    ) -> CandidateOwnerDraft:
        return CandidateOwnerDraft(
            value.proposal_ref,
            value.atomic_group_ref,
            value.basis_ordinals,
            CandidateFactClass.SUBJECTIVE_UNDERSTANDING,
            "activity",
            encode(value),
        )

    def decode(self, payload: bytes):
        return decode(payload)

    def bind_legacy(self, value: object, *, decision: bool) -> CandidateOwnerDraft:
        candidate = decode_legacy(value, decision=decision)
        if type(candidate) is CandidateActivityDraft:
            return self.bind_create(candidate)
        if type(candidate) is CandidateActivityDecisionDraft:
            return self.bind_decision(candidate)
        raise TypeError("unsupported Activity candidate")


__all__ = ("ActivityApplication",)
