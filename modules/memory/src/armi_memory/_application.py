"""Memory candidate binding application service."""

from __future__ import annotations

from armi_kernel.application import CandidateOwnerDraft

from ._codec import decode, encode
from .api import (
    CandidateMemoryDraft,
    CandidateMemoryRevisionDraft,
    MemoryFormationRequest,
    MemoryRevisionRequest,
)


class MemoryApplication:
    def bind_formation(self, request: MemoryFormationRequest) -> CandidateOwnerDraft:
        value = CandidateMemoryDraft(
            request.proposal_ref,
            request.atomic_group_ref,
            request.basis_ordinals,
            request.fact_class,
            request.source_experience_ref,
            request.source_kind,
            request.summary,
        )
        return value.owner_draft(encode(value))

    def bind_revision(self, request: MemoryRevisionRequest) -> CandidateOwnerDraft:
        value = CandidateMemoryRevisionDraft(
            request.proposal_ref,
            request.atomic_group_ref,
            request.basis_ordinals,
            request.fact_class,
            request.memory_id,
            request.current_revision_id,
            request.expected_head_version,
            request.revision_kind,
            request.accessibility,
            request.source_kind,
            request.summary,
            request.uncertainty,
            request.related_memory_id,
            request.relation_kind,
            mechanism_config_identity=request.mechanism_config_identity,
        )
        return value.owner_draft(encode(value))

    def decode(
        self, payload: bytes
    ) -> CandidateMemoryDraft | CandidateMemoryRevisionDraft:
        return decode(payload)

    def bind(
        self, value: CandidateMemoryDraft | CandidateMemoryRevisionDraft
    ) -> CandidateOwnerDraft:
        if type(value) not in {CandidateMemoryDraft, CandidateMemoryRevisionDraft}:
            raise TypeError("unsupported Memory candidate")
        return value.owner_draft(encode(value))


__all__ = ("MemoryApplication",)
