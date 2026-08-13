"""PostgreSQL writes owned by the life-material module."""

from __future__ import annotations

import json
from uuid import UUID, uuid7

from armi_kernel.application import ArtifactId, ArtifactRef, CandidateOwnerDraft
from armi_runtime_foundation import PostgreSQLTransaction

from ._application import MaterialApplication
from .api import CandidateLifeMaterialDraft, LifeMaterialRevisionKind, MaterialViolation


class PostgreSQLMaterialCommit:
    __slots__ = ("_application",)

    def __init__(self, application: MaterialApplication) -> None:
        self._application = application

    def _drafts(
        self, drafts: tuple[CandidateOwnerDraft, ...]
    ) -> tuple[CandidateLifeMaterialDraft, ...]:
        return tuple(
            self._application.decode(item.canonical_payload)
            for item in drafts
            if item.owner == "material"
        )

    async def heads_match(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        generation_id: UUID,
        drafts: tuple[CandidateOwnerDraft, ...],
    ) -> bool:
        values = self._drafts(drafts)
        for material_id in sorted({item.material_id for item in values}, key=str):
            value = next(item for item in values if item.material_id == material_id)
            row = await (
                await transaction.execute(
                    """SELECT current_revision_id,head_version,subject_id,life_generation_id,
                              owner_party_id,material_kind,deleted_at
                       FROM armi.life_materials WHERE life_material_id=%s FOR UPDATE""",
                    (material_id,),
                )
            ).fetchone()
            expected = (
                (None, 0, None, None, None, None, None)
                if value.current_revision_id is None
                else (
                    value.current_revision_id,
                    value.expected_head_version,
                    subject_id,
                    generation_id,
                    value.owner_party_id,
                    value.material_kind.value,
                    None,
                )
            )
            actual = (
                (None, 0, None, None, None, None, None)
                if row is None
                else (row[0], int(row[1]), row[2], row[3], row[4], str(row[5]), row[6])
            )
            if actual != expected:
                return False
        return True

    async def commit(
        self,
        transaction: PostgreSQLTransaction,
        *,
        validation_id: UUID,
        subject_id: UUID,
        generation_id: UUID,
        commit_id: UUID,
        drafts: tuple[CandidateOwnerDraft, ...],
        artifacts: dict[str, ArtifactRef],
    ) -> tuple[UUID, ...]:
        materials = self._drafts(drafts)
        if set(artifacts) != {
            item.proposal_ref for item in materials if item.body_bytes is not None
        }:
            raise MaterialViolation("MATERIAL-ARTIFACT")
        affected: list[UUID] = []
        for material in materials:
            revision_id = uuid7()
            reused_artifact_id: ArtifactId | None = None
            if material.current_revision_id is None:
                existing = await (
                    await transaction.execute(
                        "SELECT life_material_id FROM armi.life_materials WHERE life_material_id=%s FOR UPDATE",
                        (material.material_id,),
                    )
                ).fetchone()
                if existing is not None or material.expected_head_version != 0:
                    raise MaterialViolation("MATERIAL-HEAD-STALE")
                revision_no = 1
                previous_revision_id = None
                await transaction.execute(
                    """INSERT INTO armi.life_materials
                       (life_material_id,subject_id,life_generation_id,material_kind,
                        owner_party_id,current_revision_id,head_version)
                       VALUES (%s,%s,%s,%s,%s,%s,1)""",
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
                    await transaction.execute(
                        """SELECT material.current_revision_id,material.head_version,
                                  material.owner_party_id,material.material_kind,material.deleted_at,
                                  revision.revision_no,revision.artifact_id,revision.title,
                                  revision.metadata,revision.material_status,revision.privacy_status
                           FROM armi.life_materials AS material
                           JOIN armi.life_material_revisions AS revision
                             ON revision.life_material_revision_id=material.current_revision_id
                           WHERE material.life_material_id=%s AND material.subject_id=%s
                             AND material.life_generation_id=%s FOR UPDATE OF material""",
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
                    raise MaterialViolation("MATERIAL-HEAD-STALE")
                if material.body_bytes is None:
                    if (
                        str(current[7]) != material.title
                        or current[8] != dict(material.metadata)
                        or str(current[9]) != material.material_status.value
                        or (
                            material.revision_kind
                            is LifeMaterialRevisionKind.PRIVACY_CHANGED
                            and str(current[10]) == material.privacy_status
                        )
                    ):
                        raise MaterialViolation("MATERIAL-HEAD-STALE")
                    reused_artifact_id = ArtifactId(current[6])
                elif str(current[10]) != material.privacy_status:
                    raise MaterialViolation("MATERIAL-HEAD-STALE")
                revision_no = int(current[5]) + 1
                previous_revision_id = material.current_revision_id

            artifact = artifacts.get(material.proposal_ref)
            artifact_id = reused_artifact_id or (
                None if artifact is None else artifact.artifact_id
            )
            if artifact_id is None:
                raise MaterialViolation("MATERIAL-ARTIFACT")
            await transaction.execute(
                """INSERT INTO armi.life_material_revisions
                   (life_material_revision_id,life_material_id,revision_no,previous_revision_id,
                    subject_commit_id,candidate_validation_id,proposal_ref,artifact_id,title,
                    metadata,revision_kind,privacy_status,material_status,source_kind)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    revision_id,
                    material.material_id,
                    revision_no,
                    previous_revision_id,
                    commit_id,
                    validation_id,
                    material.proposal_ref,
                    artifact_id.value,
                    material.title,
                    json.dumps(dict(material.metadata), ensure_ascii=False),
                    material.revision_kind.value,
                    material.privacy_status,
                    material.material_status.value,
                    material.source_kind,
                ),
            )
            if previous_revision_id is not None:
                updated = await (
                    await transaction.execute(
                        """UPDATE armi.life_materials SET current_revision_id=%s,
                                  head_version=head_version+1,
                                  deleted_at=CASE WHEN %s='deleted' THEN statement_timestamp() ELSE deleted_at END,
                                  updated_at=statement_timestamp()
                           WHERE life_material_id=%s AND current_revision_id=%s AND head_version=%s
                           RETURNING life_material_id""",
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
                    raise MaterialViolation("MATERIAL-HEAD-STALE")
            affected.append(material.material_id)
        return tuple(affected)

    async def affected_material_ids(
        self, transaction: PostgreSQLTransaction, validation_id: UUID
    ) -> tuple[UUID, ...]:
        rows = await (
            await transaction.execute(
                """SELECT life_material_id FROM armi.life_material_revisions
                   WHERE candidate_validation_id=%s ORDER BY life_material_id""",
                (validation_id,),
            )
        ).fetchall()
        return tuple(row[0] for row in rows)


__all__ = ("PostgreSQLMaterialCommit",)
