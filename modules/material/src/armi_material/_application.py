"""Application services for material candidate ownership."""

from __future__ import annotations

from armi_kernel.application import CandidateFactClass, CandidateOwnerDraft

from ._codec import decode, encode
from .api import CandidateLifeMaterialDraft, MaterialViolation


class MaterialApplication:
    __slots__ = ()

    def bind(self, value: CandidateLifeMaterialDraft) -> CandidateOwnerDraft:
        if type(value) is not CandidateLifeMaterialDraft:
            raise MaterialViolation("MATERIAL-CANDIDATE")
        return CandidateOwnerDraft(
            value.proposal_ref,
            value.atomic_group_ref,
            value.basis_ordinals,
            CandidateFactClass.SUBJECTIVE_UNDERSTANDING,
            "material",
            encode(value),
        )

    def decode(self, payload: bytes) -> CandidateLifeMaterialDraft:
        return decode(payload)


__all__ = ("MaterialApplication",)
