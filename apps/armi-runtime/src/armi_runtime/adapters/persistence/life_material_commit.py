"""ARMI-owned life-material writes performed inside the T-03 transaction."""

from __future__ import annotations

import json
from typing import Any, cast
from uuid import UUID, uuid7

import rfc8785
from armi_kernel.application import (
    ArtifactId,
    CandidateLifeMaterialDraft,
    SubjectCommitViolation,
)
from armi_kernel.contracts import Digest


async def apply_life_materials(
    connection: Any,
    *,
    validation_id: UUID,
    subject_id: UUID,
    generation_id: UUID,
    commit_id: UUID,
    materials: tuple[CandidateLifeMaterialDraft, ...],
    artifact_ids: dict[str, ArtifactId],
) -> None:
    if set(artifact_ids) != {
        item.proposal_ref for item in materials if item.body_bytes is not None
    }:
        raise SubjectCommitViolation("SUBJECT-MATERIAL-ARTIFACT")
    for material in materials:
        validation = await (
            await connection.execute(
                """
                SELECT 1
                FROM armi.cognitive_candidate_validation_items
                WHERE candidate_validation_id = %s
                  AND proposal_ref = %s
                  AND owner_kind = 'material'
                  AND validation_status = 'accepted'
                """,
                (validation_id, material.proposal_ref),
            )
        ).fetchone()
        owner = await (
            await connection.execute(
                """
                SELECT 1
                FROM armi.parties
                WHERE party_id = %s
                  AND represented_subject_id = %s
                  AND party_kind = 'subject'
                """,
                (material.owner_party_id, subject_id),
            )
        ).fetchone()
        if validation is None or owner is None:
            raise SubjectCommitViolation("SUBJECT-MATERIAL-OWNER")

        revision_id = uuid7()
        reused_artifact_id: ArtifactId | None = None
        if material.current_revision_id is None:
            existing = await (
                await connection.execute(
                    """
                    SELECT life_material_id
                    FROM armi.life_materials
                    WHERE life_material_id = %s
                    FOR UPDATE
                    """,
                    (material.material_id,),
                )
            ).fetchone()
            if existing is not None or material.expected_head_version != 0:
                raise SubjectCommitViolation("SUBJECT-MATERIAL-HEAD-STALE")
            revision_no = 1
            previous_revision_id = None
            await connection.execute(
                """
                INSERT INTO armi.life_materials (
                    life_material_id, subject_id, life_generation_id,
                    material_kind, owner_party_id,
                    current_revision_id, head_version
                ) VALUES (%s, %s, %s, %s, %s, %s, 1)
                """,
                (
                    material.material_id,
                    subject_id,
                    generation_id,
                    material.material_kind.value,
                    material.owner_party_id,
                    revision_id,
                ),
            )
        else:
            current = await (
                await connection.execute(
                    """
                    SELECT material.current_revision_id,
                           material.head_version,
                           material.owner_party_id,
                           material.material_kind,
                           material.deleted_at,
                           revision.revision_no,
                           revision.artifact_id,
                           revision.body_digest,
                           revision.title,
                           revision.metadata,
                           revision.material_status,
                           revision.privacy_status
                    FROM armi.life_materials AS material
                    JOIN armi.life_material_revisions AS revision
                      ON revision.life_material_revision_id =
                         material.current_revision_id
                    WHERE material.life_material_id = %s
                      AND material.subject_id = %s
                      AND material.life_generation_id = %s
                    FOR UPDATE OF material
                    """,
                    (material.material_id, subject_id, generation_id),
                )
            ).fetchone()
            if (
                current is None
                or current[0] != material.current_revision_id
                or int(current[1]) != material.expected_head_version
                or current[2] != material.owner_party_id
                or str(current[3]) != material.material_kind.value
                or current[4] is not None
            ):
                raise SubjectCommitViolation("SUBJECT-MATERIAL-HEAD-STALE")
            if material.body_bytes is None:
                if (
                    str(current[7]) != material.body_digest.value
                    or str(current[8]) != material.title
                    or current[9] != dict(material.metadata)
                    or str(current[10]) != material.material_status.value
                    or (
                        material.revision_kind.value == "privacy_changed"
                        and str(current[11]) == material.privacy_status
                    )
                ):
                    raise SubjectCommitViolation("SUBJECT-MATERIAL-HEAD-STALE")
                reused_artifact_id = ArtifactId(current[6])
            elif str(current[11]) != material.privacy_status:
                raise SubjectCommitViolation("SUBJECT-MATERIAL-HEAD-STALE")
            revision_no = int(current[5]) + 1
            previous_revision_id = material.current_revision_id

        artifact_id = reused_artifact_id or artifact_ids.get(material.proposal_ref)
        if artifact_id is None:
            raise SubjectCommitViolation("SUBJECT-MATERIAL-ARTIFACT")
        semantic_digest = _semantic_digest(material)
        await connection.execute(
            """
            INSERT INTO armi.life_material_revisions (
                life_material_revision_id, life_material_id, revision_no,
                previous_revision_id, subject_commit_id,
                candidate_validation_id, proposal_ref, artifact_id,
                body_digest, title, metadata, revision_kind,
                privacy_status, material_status, source_kind,
                semantic_digest
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                revision_id,
                material.material_id,
                revision_no,
                previous_revision_id,
                commit_id,
                validation_id,
                material.proposal_ref,
                artifact_id.value,
                material.body_digest.value,
                material.title,
                json.dumps(dict(material.metadata), ensure_ascii=False),
                material.revision_kind.value,
                material.privacy_status,
                material.material_status.value,
                material.source_kind,
                semantic_digest.value,
            ),
        )
        if previous_revision_id is not None:
            updated = await (
                await connection.execute(
                    """
                    UPDATE armi.life_materials
                    SET current_revision_id = %s,
                        head_version = head_version + 1,
                        deleted_at = CASE
                            WHEN %s = 'deleted' THEN statement_timestamp()
                            ELSE deleted_at
                        END,
                        updated_at = statement_timestamp()
                    WHERE life_material_id = %s
                      AND current_revision_id = %s
                      AND head_version = %s
                    RETURNING life_material_id
                    """,
                    (
                        revision_id,
                        material.revision_kind.value,
                        material.material_id,
                        previous_revision_id,
                        material.expected_head_version,
                    ),
                )
            ).fetchone()
            if updated is None:
                raise SubjectCommitViolation("SUBJECT-MATERIAL-HEAD-STALE")


def _semantic_digest(material: CandidateLifeMaterialDraft) -> Digest:
    value = {
        "schema_version": "armi.life-material-revision.v2",
        "material_id": str(material.material_id),
        "owner_party_id": str(material.owner_party_id),
        "material_kind": material.material_kind.value,
        "title": material.title,
        "body_digest": material.body_digest.value,
        "metadata": dict(material.metadata),
        "material_status": material.material_status.value,
        "privacy_status": material.privacy_status,
        "revision_kind": material.revision_kind.value,
        "source_kind": material.source_kind,
    }
    return Digest.from_bytes(rfc8785.dumps(cast(Any, value)))


__all__ = ("apply_life_materials",)
