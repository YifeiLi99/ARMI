"""Canonical relationship owner payloads and stored revision codecs."""

from __future__ import annotations

import json
from typing import Any, cast
from uuid import UUID

import rfc8785
from armi_kernel.application import CandidateFactClass

from .api import (
    CandidateRelationshipDraft,
    IssueResolution,
    RelationshipBoundary,
    RelationshipBoundaryAction,
    RelationshipBoundaryKind,
    RelationshipCommitment,
    RelationshipCommitmentEvent,
    RelationshipCommitmentEventKind,
    RelationshipCommitmentStatus,
    RelationshipFact,
    RelationshipFactKind,
    RelationshipIssue,
    RelationshipIssueKind,
    RelationshipIssueStatus,
    RelationshipPartyRole,
    RelationshipStatus,
    RelationshipViolation,
)


def _relationship_dict(value: CandidateRelationshipDraft) -> dict[str, object]:
    return {
        "proposal_ref": value.proposal_ref,
        "atomic_group_ref": value.atomic_group_ref,
        "basis_ordinals": list(value.basis_ordinals),
        "fact_class": value.fact_class.value,
        "relationship_id": str(value.relationship_id),
        "subject_party_id": str(value.subject_party_id),
        "other_party_id": str(value.other_party_id),
        "current_revision_id": None
        if value.current_revision_id is None
        else str(value.current_revision_id),
        "expected_head_version": value.expected_head_version,
        "source_experience_ref": value.source_experience_ref,
        "facts": [fact_to_dict(item) for item in value.facts],
        "interpretation": value.interpretation,
        "boundaries": [boundary_to_dict(item) for item in value.boundaries],
        "status": value.status.value,
        "commitments": [commitment_to_dict(item) for item in value.commitments],
        "open_issues": [issue_to_dict(item) for item in value.open_issues],
        "commitment_event": event_to_dict(value.commitment_event),
        "issue_resolution": resolution_to_dict(value.issue_resolution),
        "reopen": value.reopen,
        "scope": value.scope,
        "mechanism_identity": value.mechanism_identity,
        "privacy_scope": value.privacy_scope,
    }


def encode_candidate(value: CandidateRelationshipDraft) -> bytes:
    return rfc8785.dumps(cast(Any, _relationship_dict(value)))


def decode_candidate(payload: bytes) -> CandidateRelationshipDraft:
    try:
        value = json.loads(payload)
        if type(value) is not dict:
            raise ValueError
        item = cast(dict[str, object], value)
        current = item["current_revision_id"]
        return CandidateRelationshipDraft(
            proposal_ref=str(item["proposal_ref"]),
            atomic_group_ref=str(item["atomic_group_ref"]),
            basis_ordinals=_integers(item["basis_ordinals"]),
            fact_class=CandidateFactClass(str(item["fact_class"])),
            relationship_id=UUID(str(item["relationship_id"])),
            subject_party_id=UUID(str(item["subject_party_id"])),
            other_party_id=UUID(str(item["other_party_id"])),
            current_revision_id=None if current is None else UUID(str(current)),
            expected_head_version=cast(int, item["expected_head_version"]),
            source_experience_ref=str(item["source_experience_ref"]),
            facts=decode_facts(item["facts"]),
            interpretation=str(item["interpretation"]),
            boundaries=decode_boundaries(item["boundaries"]),
            status=RelationshipStatus(str(item["status"])),
            commitments=decode_commitments(item["commitments"]),
            open_issues=decode_issues(item["open_issues"]),
            commitment_event=decode_event(item.get("commitment_event")),
            issue_resolution=decode_resolution(item.get("issue_resolution")),
            reopen=bool(item.get("reopen", False)),
            scope=str(item["scope"]),
            mechanism_identity=str(item["mechanism_identity"]),
            privacy_scope=str(item["privacy_scope"]),
        )
    except KeyError, TypeError, ValueError, RelationshipViolation:
        raise RelationshipViolation("RELATIONSHIP-CODEC-CANDIDATE") from None


def _objects(value: object) -> tuple[dict[str, object], ...]:
    if type(value) is not list:
        raise RelationshipViolation("RELATIONSHIP-CODEC-SHAPE")
    items = cast(list[object], value)
    if any(type(item) is not dict for item in items):
        raise RelationshipViolation("RELATIONSHIP-CODEC-SHAPE")
    return tuple(cast(dict[str, object], item) for item in items)


def _integers(value: object) -> tuple[int, ...]:
    if type(value) is not list:
        raise RelationshipViolation("RELATIONSHIP-CODEC-SHAPE")
    items = cast(list[object], value)
    if any(type(item) is not int for item in items):
        raise RelationshipViolation("RELATIONSHIP-CODEC-SHAPE")
    return tuple(cast(int, item) for item in items)


def fact_to_dict(value: RelationshipFact) -> dict[str, object]:
    return {
        "fact_id": str(value.fact_id),
        "kind": value.kind.value,
        "summary": value.summary,
    }


def decode_facts(value: object) -> tuple[RelationshipFact, ...]:
    return tuple(
        RelationshipFact(
            UUID(str(item["fact_id"])),
            RelationshipFactKind(str(item["kind"])),
            str(item["summary"]),
        )
        for item in _objects(value)
    )


def boundary_to_dict(value: RelationshipBoundary) -> dict[str, object]:
    return {
        "party_role": value.party_role.value,
        "kind": value.kind.value,
        "action": value.action.value,
        "summary": value.summary,
    }


def decode_boundaries(value: object) -> tuple[RelationshipBoundary, ...]:
    return tuple(
        RelationshipBoundary(
            RelationshipPartyRole(str(item["party_role"])),
            RelationshipBoundaryKind(str(item["kind"])),
            RelationshipBoundaryAction(str(item["action"])),
            str(item["summary"]),
        )
        for item in _objects(value)
    )


def commitment_to_dict(value: RelationshipCommitment) -> dict[str, object]:
    return {
        "commitment_id": str(value.commitment_id),
        "party_role": value.party_role.value,
        "scope": value.scope,
        "content": value.content,
        "status": value.status.value,
        "last_event_kind": value.last_event_kind.value,
        "last_event_summary": value.last_event_summary,
    }


def decode_commitments(value: object) -> tuple[RelationshipCommitment, ...]:
    return tuple(
        RelationshipCommitment(
            UUID(str(item["commitment_id"])),
            RelationshipPartyRole(str(item["party_role"])),
            str(item["scope"]),
            str(item["content"]),
            RelationshipCommitmentStatus(str(item["status"])),
            RelationshipCommitmentEventKind(str(item["last_event_kind"])),
            str(item["last_event_summary"]),
        )
        for item in _objects(value)
    )


def issue_to_dict(value: RelationshipIssue) -> dict[str, object]:
    return {
        "issue_id": str(value.issue_id),
        "kind": value.kind.value,
        "commitment_ids": [str(item) for item in value.commitment_ids],
        "summary": value.summary,
        "status": value.status.value,
    }


def decode_issues(value: object) -> tuple[RelationshipIssue, ...]:
    return tuple(
        RelationshipIssue(
            UUID(str(item["issue_id"])),
            RelationshipIssueKind(str(item["kind"])),
            tuple(UUID(str(v)) for v in cast(list[object], item["commitment_ids"])),
            str(item["summary"]),
            RelationshipIssueStatus(str(item["status"])),
        )
        for item in _objects(value)
    )


def event_to_dict(
    value: RelationshipCommitmentEvent | None,
) -> dict[str, object] | None:
    if value is None:
        return None
    return {
        "commitment_id": str(value.commitment_id),
        "kind": value.kind.value,
        "summary": value.summary,
        "related_commitment_id": None
        if value.related_commitment_id is None
        else str(value.related_commitment_id),
    }


def decode_event(value: object) -> RelationshipCommitmentEvent | None:
    if value is None:
        return None
    item = cast(dict[str, object], value)
    related = item["related_commitment_id"]
    return RelationshipCommitmentEvent(
        UUID(str(item["commitment_id"])),
        RelationshipCommitmentEventKind(str(item["kind"])),
        str(item["summary"]),
        None if related is None else UUID(str(related)),
    )


def resolution_to_dict(value: IssueResolution | None) -> dict[str, object] | None:
    if value is None:
        return None
    return {
        "issue_id": str(value.issue_id),
        "status": value.status.value,
        "resolution_summary": value.resolution_summary,
    }


def decode_resolution(value: object) -> IssueResolution | None:
    if value is None:
        return None
    item = cast(dict[str, object], value)
    return IssueResolution(
        UUID(str(item["issue_id"])),
        RelationshipIssueStatus(str(item["status"])),
        str(item["resolution_summary"]),
    )


__all__ = (
    "boundary_to_dict",
    "commitment_to_dict",
    "decode_boundaries",
    "decode_candidate",
    "decode_commitments",
    "decode_event",
    "decode_facts",
    "decode_issues",
    "decode_resolution",
    "encode_candidate",
    "event_to_dict",
    "fact_to_dict",
    "issue_to_dict",
    "resolution_to_dict",
)
