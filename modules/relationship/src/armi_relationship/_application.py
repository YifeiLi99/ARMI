"""Relationship lifecycle binding and policy implementation."""

from __future__ import annotations

from armi_kernel.application import CandidateOwnerDraft

from ._codec import decode_candidate, encode_candidate
from .api import (
    CandidateRelationshipDraft,
    RelationshipBoundaryAction,
    RelationshipBoundaryKind,
    RelationshipSnapshot,
    RelationshipViolation,
)


class RelationshipApplication:
    def bind(self, candidate: object) -> CandidateOwnerDraft:
        if type(candidate) is not CandidateRelationshipDraft:
            raise RelationshipViolation("RELATIONSHIP-COGNITION-CANDIDATE")
        value = candidate
        canonical_payload = encode_candidate(value)
        return value.owner_draft(canonical_payload)

    def decode_change_set(self, payload: bytes) -> CandidateRelationshipDraft:
        return decode_candidate(payload)

    def allows_contact(self, relationship: CandidateRelationshipDraft) -> bool:
        return not self._blocks_contact(relationship)

    def allows_reply(self, relationship: CandidateRelationshipDraft) -> bool:
        return not self._blocks_contact(relationship)

    def allows_outreach(self, relationship: CandidateRelationshipDraft) -> bool:
        return not self._blocks_contact(relationship)

    def allows_snapshot_contact(self, relationship: RelationshipSnapshot) -> bool:
        return relationship.revision.status.value != "ended" and not any(
            boundary.kind
            in {RelationshipBoundaryKind.CONTACT, RelationshipBoundaryKind.EXIT}
            and boundary.action
            in {
                RelationshipBoundaryAction.REFUSE,
                RelationshipBoundaryAction.RESTRICT,
                RelationshipBoundaryAction.END_CONTACT,
            }
            for boundary in relationship.revision.boundaries
        )

    def allows_snapshot_outreach(self, relationship: RelationshipSnapshot) -> bool:
        return self.allows_snapshot_contact(relationship)

    @staticmethod
    def _blocks_contact(relationship: CandidateRelationshipDraft) -> bool:
        return relationship.status.value == "ended" or any(
            boundary.kind
            in {RelationshipBoundaryKind.CONTACT, RelationshipBoundaryKind.EXIT}
            and boundary.action
            in {
                RelationshipBoundaryAction.REFUSE,
                RelationshipBoundaryAction.END_CONTACT,
            }
            for boundary in relationship.boundaries
        )


__all__ = ("RelationshipApplication",)
