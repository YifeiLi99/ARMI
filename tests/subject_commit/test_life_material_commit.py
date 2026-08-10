from __future__ import annotations

import json
from typing import Any, cast
from uuid import UUID, uuid7

import pytest
from armi_kernel.application import (
    ArtifactId,
    ArtifactIntegrityStatus,
    ArtifactPrivacyScope,
    ArtifactRef,
    CandidateLifeMaterialDraft,
    LifeMaterialKind,
    LifeMaterialRevisionKind,
    LifeMaterialStatus,
    SubjectCommitViolation,
)
from armi_kernel.contracts import Digest
from armi_runtime.adapters.persistence.life_material_commit import (
    apply_life_materials,
)


class _Result:
    def __init__(self, row: tuple[object, ...] | None = None) -> None:
        self._row = row

    async def fetchone(self) -> tuple[object, ...] | None:
        return self._row


class _MaterialConnection:
    def __init__(self, *, subject_id: UUID, owner_party_id: UUID) -> None:
        self.subject_id = subject_id
        self.owner_party_id = owner_party_id
        self.materials: dict[UUID, dict[str, Any]] = {}
        self.revisions: list[tuple[object, ...]] = []

    async def execute(
        self,
        query: str,
        params: tuple[object, ...] = (),
    ) -> _Result:
        if "FROM armi.cognitive_candidate_validation_items" in query:
            return _Result((1,))
        if "FROM armi.parties" in query:
            return _Result(
                (1,) if params == (self.owner_party_id, self.subject_id) else None
            )
        if "SELECT life_material_id" in query:
            material_id = cast(UUID, params[0])
            return _Result((material_id,) if material_id in self.materials else None)
        if "INSERT INTO armi.life_materials" in query:
            material_id = cast(UUID, params[0])
            self.materials[material_id] = {
                "subject_id": params[1],
                "generation_id": params[2],
                "kind": params[3],
                "owner": params[4],
                "current_revision_id": params[5],
                "head_version": 1,
                "deleted_at": None,
            }
            return _Result()
        if "SELECT material.current_revision_id" in query:
            material = self.materials.get(cast(UUID, params[0]))
            if (
                material is None
                or material["subject_id"] != params[1]
                or material["generation_id"] != params[2]
            ):
                return _Result()
            revision_no = next(
                cast(int, row[2])
                for row in reversed(self.revisions)
                if row[0] == material["current_revision_id"]
            )
            revision = next(
                row
                for row in reversed(self.revisions)
                if row[0] == material["current_revision_id"]
            )
            return _Result(
                (
                    material["current_revision_id"],
                    material["head_version"],
                    material["owner"],
                    material["kind"],
                    material["deleted_at"],
                    revision_no,
                    revision[7],
                    revision[8],
                    json.loads(cast(str, revision[9])),
                    revision[12],
                    revision[11],
                )
            )
        if "INSERT INTO armi.life_material_revisions" in query:
            self.revisions.append(params)
            return _Result()
        if "UPDATE armi.life_materials" in query:
            material = self.materials.get(cast(UUID, params[2]))
            if (
                material is None
                or material["current_revision_id"] != params[3]
                or material["head_version"] != params[4]
            ):
                return _Result()
            material["current_revision_id"] = params[0]
            material["head_version"] = int(material["head_version"]) + 1
            if params[1] == "deleted":
                material["deleted_at"] = "deleted"
            return _Result((params[2],))
        raise AssertionError(f"unexpected SQL: {query}")


def _draft(
    *,
    material_id: UUID,
    owner_party_id: UUID,
    current_revision_id: UUID | None,
    head_version: int,
    body: str,
) -> CandidateLifeMaterialDraft:
    body_bytes = body.encode()
    return CandidateLifeMaterialDraft(
        "proposal:1",
        "group:1",
        (2,) if current_revision_id is None else (2, 6),
        material_id,
        owner_party_id,
        LifeMaterialKind.WORK,
        current_revision_id,
        head_version,
        "一份作品",
        body_bytes,
        (("topic", "reflection"),),
        LifeMaterialStatus.ACTIVE,
    )


def _state_draft(
    *,
    material_id: UUID,
    owner_party_id: UUID,
    current_revision_id: UUID,
    head_version: int,
    privacy_status: str,
    revision_kind: LifeMaterialRevisionKind,
) -> CandidateLifeMaterialDraft:
    return CandidateLifeMaterialDraft(
        "proposal:1",
        "group:1",
        (2, 6),
        material_id,
        owner_party_id,
        LifeMaterialKind.WORK,
        current_revision_id,
        head_version,
        "一份作品",
        None,
        (("topic", "reflection"),),
        LifeMaterialStatus.ACTIVE,
        privacy_status,
        change_kind=revision_kind,
    )


def _artifact(artifact_id: ArtifactId, content: bytes) -> ArtifactRef:
    return ArtifactRef(
        artifact_id,
        Digest.from_bytes(content),
        len(content),
        "application/json",
        "life_material_content",
        ArtifactPrivacyScope.PRIVATE,
        ArtifactIntegrityStatus.VERIFIED,
    )


@pytest.mark.asyncio
async def test_life_material_commit_appends_revision_and_cas_updates_head() -> None:
    subject_id, generation_id, owner_party_id = uuid7(), uuid7(), uuid7()
    material_id = uuid7()
    connection = _MaterialConnection(
        subject_id=subject_id,
        owner_party_id=owner_party_id,
    )
    created = _draft(
        material_id=material_id,
        owner_party_id=owner_party_id,
        current_revision_id=None,
        head_version=0,
        body="第一版正文",
    )
    first_artifact = ArtifactId(uuid7())
    await apply_life_materials(
        connection,
        validation_id=uuid7(),
        subject_id=subject_id,
        generation_id=generation_id,
        commit_id=uuid7(),
        materials=(created,),
        artifacts={"proposal:1": _artifact(first_artifact, created.body_bytes or b"")},
    )
    first_revision_id = connection.materials[material_id]["current_revision_id"]
    assert connection.materials[material_id]["head_version"] == 1
    assert connection.revisions[0][3] is None
    assert connection.revisions[0][7] == first_artifact.value
    assert connection.revisions[0][10] == "created"

    updated = _draft(
        material_id=material_id,
        owner_party_id=owner_party_id,
        current_revision_id=first_revision_id,
        head_version=1,
        body="完整替换后的第二版正文",
    )
    second_artifact = ArtifactId(uuid7())
    await apply_life_materials(
        connection,
        validation_id=uuid7(),
        subject_id=subject_id,
        generation_id=generation_id,
        commit_id=uuid7(),
        materials=(updated,),
        artifacts={"proposal:1": _artifact(second_artifact, updated.body_bytes or b"")},
    )
    assert connection.materials[material_id]["head_version"] == 2
    assert connection.revisions[1][2] == 2
    assert connection.revisions[1][3] == first_revision_id
    assert connection.revisions[1][7] == second_artifact.value
    assert connection.revisions[1][10] == "updated"


@pytest.mark.asyncio
async def test_life_material_privacy_and_delete_reuse_artifact_then_tombstone() -> None:
    subject_id, generation_id, owner_party_id = uuid7(), uuid7(), uuid7()
    material_id = uuid7()
    connection = _MaterialConnection(
        subject_id=subject_id,
        owner_party_id=owner_party_id,
    )
    created = _draft(
        material_id=material_id,
        owner_party_id=owner_party_id,
        current_revision_id=None,
        head_version=0,
        body="不会因隐私或删除而重写的正文",
    )
    artifact_id = ArtifactId(uuid7())
    await apply_life_materials(
        connection,
        validation_id=uuid7(),
        subject_id=subject_id,
        generation_id=generation_id,
        commit_id=uuid7(),
        materials=(created,),
        artifacts={"proposal:1": _artifact(artifact_id, created.body_bytes or b"")},
    )
    first_revision_id = cast(
        UUID, connection.materials[material_id]["current_revision_id"]
    )
    private = _state_draft(
        material_id=material_id,
        owner_party_id=owner_party_id,
        current_revision_id=first_revision_id,
        head_version=1,
        privacy_status="private",
        revision_kind=LifeMaterialRevisionKind.PRIVACY_CHANGED,
    )
    await apply_life_materials(
        connection,
        validation_id=uuid7(),
        subject_id=subject_id,
        generation_id=generation_id,
        commit_id=uuid7(),
        materials=(private,),
        artifacts={},
    )
    assert connection.revisions[1][7] == artifact_id.value
    assert connection.revisions[1][10:12] == ("privacy_changed", "private")

    private_revision_id = cast(
        UUID, connection.materials[material_id]["current_revision_id"]
    )
    deleted = _state_draft(
        material_id=material_id,
        owner_party_id=owner_party_id,
        current_revision_id=private_revision_id,
        head_version=2,
        privacy_status="restricted",
        revision_kind=LifeMaterialRevisionKind.DELETED,
    )
    await apply_life_materials(
        connection,
        validation_id=uuid7(),
        subject_id=subject_id,
        generation_id=generation_id,
        commit_id=uuid7(),
        materials=(deleted,),
        artifacts={},
    )
    assert connection.revisions[2][7] == artifact_id.value
    assert connection.revisions[2][10:12] == ("deleted", "restricted")
    assert connection.materials[material_id]["deleted_at"] == "deleted"

    deleted_revision_id = cast(
        UUID, connection.materials[material_id]["current_revision_id"]
    )
    update_after_delete = _draft(
        material_id=material_id,
        owner_party_id=owner_party_id,
        current_revision_id=deleted_revision_id,
        head_version=3,
        body="试图恢复已删除资料",
    )
    with pytest.raises(SubjectCommitViolation) as terminal:
        await apply_life_materials(
            connection,
            validation_id=uuid7(),
            subject_id=subject_id,
            generation_id=generation_id,
            commit_id=uuid7(),
            materials=(update_after_delete,),
            artifacts={
                "proposal:1": _artifact(ArtifactId(uuid7()), update_after_delete.body_bytes or b"")
            },
        )
    assert terminal.value.code == "SUBJECT-MATERIAL-HEAD-STALE"


@pytest.mark.asyncio
async def test_life_material_commit_rejects_duplicate_create_and_missing_artifact() -> (
    None
):
    subject_id, generation_id, owner_party_id = uuid7(), uuid7(), uuid7()
    material_id = uuid7()
    connection = _MaterialConnection(
        subject_id=subject_id,
        owner_party_id=owner_party_id,
    )
    draft = _draft(
        material_id=material_id,
        owner_party_id=owner_party_id,
        current_revision_id=None,
        head_version=0,
        body="正文",
    )
    arguments = {
        "validation_id": uuid7(),
        "subject_id": subject_id,
        "generation_id": generation_id,
        "commit_id": uuid7(),
        "materials": (draft,),
    }
    with pytest.raises(SubjectCommitViolation) as missing:
        await apply_life_materials(connection, **arguments, artifacts={})
    assert missing.value.code == "SUBJECT-MATERIAL-ARTIFACT"

    await apply_life_materials(
        connection,
        **arguments,
        artifacts={"proposal:1": _artifact(ArtifactId(uuid7()), draft.body_bytes or b"")},
    )
    with pytest.raises(SubjectCommitViolation) as duplicate:
        await apply_life_materials(
            connection,
            **arguments,
            artifacts={"proposal:1": _artifact(ArtifactId(uuid7()), draft.body_bytes or b"")},
        )
    assert duplicate.value.code == "SUBJECT-MATERIAL-HEAD-STALE"
