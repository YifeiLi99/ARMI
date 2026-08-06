"""Relationship-owned writes performed inside the T-03 transaction."""

from __future__ import annotations

import json
from typing import Any, cast
from uuid import UUID, uuid7

import rfc8785
from armi_kernel.application import (
    CandidateRelationshipDraft,
    SubjectCommitViolation,
)
from armi_kernel.contracts import Digest


async def apply_relationships(
    connection: Any,
    *,
    validation_id: UUID,
    subject_id: UUID,
    generation_id: UUID,
    creator_party_id: UUID | None,
    episode_other_party_id: UUID | None = None,
    commit_id: UUID,
    relationships: tuple[CandidateRelationshipDraft, ...],
    experience_ids: dict[str, UUID],
) -> None:
    for relationship in relationships:
        validation = await (
            await connection.execute(
                """
                SELECT 1
                FROM armi.cognitive_candidate_validation_items
                WHERE candidate_validation_id = %s
                  AND proposal_ref = %s
                  AND owner_kind = 'relationship'
                  AND validation_status = 'accepted'
                """,
                (validation_id, relationship.proposal_ref),
            )
        ).fetchone()
        source_experience_id = experience_ids.get(relationship.source_experience_ref)
        if validation is None or source_experience_id is None:
            raise SubjectCommitViolation("SUBJECT-RELATIONSHIP-VALIDATION")
        expected_other_party_id = (
            creator_party_id
            if relationship.scope == "creator_social"
            else episode_other_party_id
        )
        if expected_other_party_id != relationship.other_party_id:
            raise SubjectCommitViolation("SUBJECT-RELATIONSHIP-PARTY")
        parties = await (
            await connection.execute(
                """
                SELECT 1
                FROM armi.parties AS subject_party
                JOIN armi.parties AS other_party ON other_party.party_id = %s
                WHERE subject_party.party_id = %s
                  AND subject_party.party_kind = 'subject'
                  AND subject_party.represented_subject_id = %s
                  AND (
                      (
                          %s = 'creator_social'
                          AND other_party.party_kind = 'creator'
                          AND other_party.creator_role = 'unique_primary_creator'
                      )
                      OR (
                          %s = 'other_human_social'
                          AND other_party.party_kind = 'other_human'
                          AND other_party.creator_role IS NULL
                          AND other_party.declared_identity_key IS NOT NULL
                      )
                  )
                """,
                (
                    relationship.other_party_id,
                    relationship.subject_party_id,
                    subject_id,
                    relationship.scope,
                    relationship.scope,
                ),
            )
        ).fetchone()
        if parties is None:
            raise SubjectCommitViolation("SUBJECT-RELATIONSHIP-PARTY")

        facts = [
            {"kind": item.kind.value, "summary": item.summary}
            for item in relationship.facts
        ]
        boundaries = [
            {
                "party_role": item.party_role.value,
                "kind": item.kind.value,
                "action": item.action.value,
                "summary": item.summary,
            }
            for item in relationship.boundaries
        ]
        commitments = [
            {
                "commitment_id": str(item.commitment_id),
                "party_role": item.party_role.value,
                "scope": item.scope,
                "content": item.content,
                "status": item.status.value,
                "last_event_kind": item.last_event_kind.value,
                "last_event_summary": item.last_event_summary,
            }
            for item in relationship.commitments
        ]
        open_issues = [
            {
                "issue_id": str(item.issue_id),
                "kind": item.kind.value,
                "commitment_ids": [str(value) for value in item.commitment_ids],
                "summary": item.summary,
                "status": item.status.value,
            }
            for item in relationship.open_issues
        ]
        commitment_event = (
            None
            if relationship.commitment_event is None
            else {
                "commitment_id": str(relationship.commitment_event.commitment_id),
                "kind": relationship.commitment_event.kind.value,
                "summary": relationship.commitment_event.summary,
                "related_commitment_id": (
                    None
                    if relationship.commitment_event.related_commitment_id is None
                    else str(relationship.commitment_event.related_commitment_id)
                ),
            }
        )
        semantic_bytes = rfc8785.dumps(
            cast(
                Any,
                {
                    "schema_version": "armi.relationship-revision.v2",
                    "facts": facts,
                    "interpretation": relationship.interpretation,
                    "boundaries": boundaries,
                    "commitments": commitments,
                    "open_issues": open_issues,
                    "commitment_event": commitment_event,
                    "status": relationship.status.value,
                },
            )
        )
        revision_id = uuid7()
        if relationship.current_revision_id is None:
            existing = await (
                await connection.execute(
                    """
                    SELECT relationship_id
                    FROM armi.relationships
                    WHERE subject_id = %s
                      AND other_party_id = %s
                      AND scope = %s
                    FOR UPDATE
                    """,
                    (subject_id, relationship.other_party_id, relationship.scope),
                )
            ).fetchone()
            if existing is not None or relationship.expected_head_version != 0:
                raise SubjectCommitViolation("SUBJECT-RELATIONSHIP-HEAD-STALE")
            revision_no = 1
            previous_revision_id = None
            await connection.execute(
                """
                INSERT INTO armi.relationships (
                    relationship_id, subject_id, life_generation_id,
                    subject_party_id, other_party_id, scope,
                    current_revision_id, head_version
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, 1)
                """,
                (
                    relationship.relationship_id,
                    subject_id,
                    generation_id,
                    relationship.subject_party_id,
                    relationship.other_party_id,
                    relationship.scope,
                    revision_id,
                ),
            )
        else:
            current = await (
                await connection.execute(
                    """
                    SELECT relationship.current_revision_id,
                           relationship.head_version,
                           relationship.subject_party_id,
                           relationship.other_party_id,
                           relationship.scope,
                           revision.revision_no,
                           revision.relationship_status
                    FROM armi.relationships AS relationship
                    JOIN armi.relationship_revisions AS revision
                      ON revision.relationship_revision_id =
                         relationship.current_revision_id
                    WHERE relationship.relationship_id = %s
                      AND relationship.subject_id = %s
                      AND relationship.life_generation_id = %s
                    FOR UPDATE OF relationship
                    """,
                    (relationship.relationship_id, subject_id, generation_id),
                )
            ).fetchone()
            if (
                current is None
                or current[0] != relationship.current_revision_id
                or int(current[1]) != relationship.expected_head_version
                or current[2] != relationship.subject_party_id
                or current[3] != relationship.other_party_id
                or str(current[4]) != relationship.scope
                or str(current[6]) == "ended"
            ):
                raise SubjectCommitViolation("SUBJECT-RELATIONSHIP-HEAD-STALE")
            revision_no = int(current[5]) + 1
            previous_revision_id = relationship.current_revision_id

        await connection.execute(
            """
            INSERT INTO armi.relationship_revisions (
                relationship_revision_id, relationship_id, revision_no,
                previous_revision_id, subject_commit_id,
                candidate_validation_id, proposal_ref, facts,
                interpretation, boundaries, commitments, open_issues,
                commitment_event, relationship_status,
                semantic_digest, mechanism_identity, privacy_scope
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s,
                'private'
            )
            """,
            (
                revision_id,
                relationship.relationship_id,
                revision_no,
                previous_revision_id,
                commit_id,
                validation_id,
                relationship.proposal_ref,
                json.dumps(facts, ensure_ascii=False),
                relationship.interpretation,
                json.dumps(boundaries, ensure_ascii=False),
                json.dumps(commitments, ensure_ascii=False),
                json.dumps(open_issues, ensure_ascii=False),
                (
                    None
                    if commitment_event is None
                    else json.dumps(commitment_event, ensure_ascii=False)
                ),
                relationship.status.value,
                Digest.from_bytes(semantic_bytes).value,
                relationship.mechanism_identity,
            ),
        )
        if previous_revision_id is not None:
            updated = await (
                await connection.execute(
                    """
                    UPDATE armi.relationships
                    SET current_revision_id = %s,
                        head_version = head_version + 1
                    WHERE relationship_id = %s
                      AND current_revision_id = %s
                      AND head_version = %s
                    RETURNING relationship_id
                    """,
                    (
                        revision_id,
                        relationship.relationship_id,
                        previous_revision_id,
                        relationship.expected_head_version,
                    ),
                )
            ).fetchone()
            if updated is None:
                raise SubjectCommitViolation("SUBJECT-RELATIONSHIP-HEAD-STALE")
        await connection.execute(
            """
            INSERT INTO armi.relationship_experience_links (
                relationship_revision_id, experience_id, link_kind, ordinal
            ) VALUES (%s, %s, %s, 1)
            """,
            (
                revision_id,
                source_experience_id,
                (
                    "supports_commitment_event"
                    if relationship.commitment_event is not None
                    else "supports_relationship_change"
                ),
            ),
        )


__all__ = ("apply_relationships",)
