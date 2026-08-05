from __future__ import annotations

from typing import Any, cast
from uuid import UUID, uuid7

import pytest
from armi_kernel.application import (
    ArtifactId,
    CandidateLifeMaterialDraft,
    LifeMaterialKind,
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
            return _Result(
                (
                    material["current_revision_id"],
                    material["head_version"],
                    material["owner"],
                    material["kind"],
                    material["deleted_at"],
                    revision_no,
                )
            )
        if "INSERT INTO armi.life_material_revisions" in query:
            self.revisions.append(params)
            return _Result()
        if "UPDATE armi.life_materials" in query:
            material = self.materials.get(cast(UUID, params[1]))
            if (
                material is None
                or material["current_revision_id"] != params[2]
                or material["head_version"] != params[3]
            ):
                return _Result()
            material["current_revision_id"] = params[0]
            material["head_version"] = int(material["head_version"]) + 1
            return _Result((params[1],))
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
        Digest.from_bytes(body_bytes),
        (("topic", "reflection"),),
        LifeMaterialStatus.ACTIVE,
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
        artifact_ids={"proposal:1": first_artifact},
    )
    first_revision_id = connection.materials[material_id]["current_revision_id"]
    assert connection.materials[material_id]["head_version"] == 1
    assert connection.revisions[0][3] is None
    assert connection.revisions[0][7] == first_artifact.value
    assert connection.revisions[0][11] == "created"

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
        artifact_ids={"proposal:1": second_artifact},
    )
    assert connection.materials[material_id]["head_version"] == 2
    assert connection.revisions[1][2] == 2
    assert connection.revisions[1][3] == first_revision_id
    assert connection.revisions[1][7] == second_artifact.value
    assert connection.revisions[1][11] == "updated"


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
        await apply_life_materials(connection, **arguments, artifact_ids={})
    assert missing.value.code == "SUBJECT-MATERIAL-ARTIFACT"

    await apply_life_materials(
        connection,
        **arguments,
        artifact_ids={"proposal:1": ArtifactId(uuid7())},
    )
    with pytest.raises(SubjectCommitViolation) as duplicate:
        await apply_life_materials(
            connection,
            **arguments,
            artifact_ids={"proposal:1": ArtifactId(uuid7())},
        )
    assert duplicate.value.code == "SUBJECT-MATERIAL-HEAD-STALE"
