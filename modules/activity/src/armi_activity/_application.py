"""Activity candidate binding application service."""

from __future__ import annotations

from armi_kernel.application import CandidateFactClass, CandidateOwnerDraft

from ._codec import decode, encode
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

    def bind(
        self, value: CandidateActivityDraft | CandidateActivityDecisionDraft
    ) -> CandidateOwnerDraft:
        if type(value) is CandidateActivityDraft:
            return self.bind_create(value)
        if type(value) is CandidateActivityDecisionDraft:
            return self.bind_decision(value)
        raise TypeError("unsupported Activity candidate")


__all__ = ("ActivityApplication",)
