"""Package-private PostgreSQL write surface for the unique birth transaction."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID, uuid7

import psycopg
from armi_kernel.application import BirthManifest, BirthResult, BirthViolation
from armi_kernel.contracts import Digest

from .unit_of_work import PostgreSQLUnitOfWork

_SELF: dict[str, object] = {
    "schema_version": "armi.self.v1",
    "identity_kind": "electronic_person",
    "creator_role_awareness": "unique_primary_creator",
    "name": None,
    "self_description": None,
    "interests": [],
    "values": [],
    "preferences": [],
    "goals": [],
    "self_narrative": None,
    "tensions": [],
}
_MIND: dict[str, object] = {
    "schema_version": "armi.mind.v1",
    "understanding": [],
    "attention": [],
    "emotions": [],
    "thoughts": [],
    "wishes": [],
    "motivations": [],
    "mood": None,
}
_LIFE_MODE: dict[str, object] = {
    "schema_version": "armi.life-mode.v1",
    "mode": "awake",
    "active_activities": [],
}


class ContinuityState(StrEnum):
    UNBORN = "unborn"
    BORN = "born"
    INVALID = "invalid"


def probe_continuity(
    conninfo: str,
    *,
    composition_digest: Digest,
    schema_manifest_digest: Digest,
    birth_contract_digest: Digest,
    creator_asset_digest: Digest,
) -> ContinuityState:
    try:
        with psycopg.connect(conninfo, autocommit=True) as connection:
            rows = connection.execute(
                """
                SELECT
                    subject.subject_id,
                    activation.bundle_digest,
                    activation.schema_baseline_digest,
                    activation.fixed_policy_digest,
                    activation.creator_asset_digest,
                    (
                        SELECT count(*) FROM armi.life_generations
                        WHERE subject_id = subject.subject_id
                          AND life_generation_id = subject.current_generation_id
                          AND generation_no = 1 AND status = 'active'
                    ),
                    (
                        SELECT count(*) FROM armi.parties
                        WHERE represented_subject_id = subject.subject_id
                           OR creator_role = 'unique_primary_creator'
                    ),
                    (
                        SELECT count(*) FROM armi.prompt_documents
                        WHERE subject_id = subject.subject_id
                    ),
                    (
                        SELECT count(*) FROM armi.prompt_revisions AS revision
                        JOIN armi.prompt_documents AS document
                          ON document.prompt_document_id = revision.prompt_document_id
                        WHERE document.subject_id = subject.subject_id
                    ),
                    (
                        SELECT count(*) FROM armi.subject_component_heads
                        WHERE subject_id = subject.subject_id
                    ),
                    (
                        SELECT count(*) FROM armi.subject_component_revisions
                        WHERE subject_id = subject.subject_id
                    ),
                    (
                        SELECT count(*) FROM armi.interaction_scenes
                        WHERE subject_id = subject.subject_id
                          AND scene_key = 'default'
                          AND scene_kind = 'creator_dialogue'
                          AND audience_scope = 'creator'
                          AND current_status = 'open'
                          AND closed_at IS NULL
                    )
                FROM armi.subjects AS subject
                JOIN armi.runtime_bundle_activations AS activation
                  ON activation.bundle_activation_id =
                     subject.current_bundle_activation_id
                ORDER BY subject.singleton_key
                """
            ).fetchall()
            if not rows:
                counts = connection.execute(
                    """
                    SELECT
                        (SELECT count(*) FROM armi.life_generations)
                      + (SELECT count(*) FROM armi.runtime_bundle_activations)
                      + (SELECT count(*) FROM armi.parties)
                      + (SELECT count(*) FROM armi.prompt_documents)
                      + (SELECT count(*) FROM armi.prompt_revisions)
                      + (SELECT count(*) FROM armi.subject_component_heads)
                      + (SELECT count(*) FROM armi.subject_component_revisions)
                      + (SELECT count(*) FROM armi.interaction_scenes)
                      + (SELECT count(*) FROM armi.scene_timeline_items)
                    """
                ).fetchone()
                return (
                    ContinuityState.UNBORN
                    if counts is not None and counts[0] == 0
                    else ContinuityState.INVALID
                )
    except psycopg.Error:
        return ContinuityState.INVALID
    if len(rows) != 1:
        return ContinuityState.INVALID
    row = rows[0]
    expected = (
        composition_digest.value,
        schema_manifest_digest.value,
        birth_contract_digest.value,
        creator_asset_digest.value,
    )
    if tuple(str(value) for value in row[1:5]) != expected:
        return ContinuityState.INVALID
    if tuple(int(value) for value in row[5:]) != (1, 2, 3, 1, 3, 3, 1):
        return ContinuityState.INVALID
    return ContinuityState.BORN


@dataclass(frozen=True, slots=True)
class BirthArtifacts:
    anchor_artifact_id: UUID
    activation_artifact_id: UUID
    fixed_prompt_set_digest: Digest


class BirthRepository:
    """Write all birth facts through the caller's active SERIALIZABLE UoW."""

    __slots__ = ()

    async def lock_environment(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        environment_id: UUID,
    ) -> None:
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        await connection.execute(
            "SELECT pg_catalog.pg_advisory_xact_lock("
            "pg_catalog.hashtextextended(%s, 0))",
            (f"armi.birth:{environment_id}",),
        )

    async def existing(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        manifest: BirthManifest,
    ) -> BirthResult | None:
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        rows = await (
            await connection.execute(
                """
                SELECT
                    subject_id,
                    current_generation_id,
                    current_bundle_activation_id,
                    birth_request_id,
                    birth_idempotency_key,
                    birth_manifest_digest
                FROM armi.subjects
                ORDER BY singleton_key
                """
            )
        ).fetchall()
        if not rows:
            return None
        if len(rows) != 1:
            raise BirthViolation("BIRTH-STATE-DIRTY")
        row = rows[0]
        if (
            row[3] == manifest.birth_request_id
            and str(row[4]) == manifest.idempotency_key
            and str(row[5]) == manifest.request_digest.value
        ):
            return BirthResult(
                subject_id=row[0],
                life_generation_id=row[1],
                bundle_activation_id=row[2],
                request_digest=manifest.request_digest,
                created=False,
            )
        if str(row[4]) == manifest.idempotency_key:
            raise BirthViolation("BIRTH-IDEMPOTENCY-CONFLICT")
        raise BirthViolation("BIRTH-ALREADY-BORN")

    async def create(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        manifest: BirthManifest,
        artifacts: BirthArtifacts,
    ) -> BirthResult:
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        subject_id = uuid7()
        generation_id = uuid7()
        activation_id = uuid7()
        subject_party_id = uuid7()
        default_scene_id = uuid7()
        anchor_document_id = uuid7()
        creator_document_id = uuid7()
        subject_document_id = uuid7()
        anchor_revision_id = uuid7()
        component_revisions = {kind: uuid7() for kind in ("self", "mind", "life_mode")}
        await connection.execute(
            """
            INSERT INTO armi.subjects (
                subject_id, singleton_key, birth_request_id,
                birth_idempotency_key, birth_manifest_digest,
                current_generation_id, current_bundle_activation_id
            ) VALUES (%s, 1, %s, %s, %s, %s, %s)
            """,
            (
                subject_id,
                manifest.birth_request_id,
                manifest.idempotency_key,
                manifest.request_digest.value,
                generation_id,
                activation_id,
            ),
        )
        await connection.execute(
            """
            INSERT INTO armi.life_generations (
                life_generation_id, subject_id, generation_no, status,
                opened_subject_version, activation_reason
            ) VALUES (%s, %s, 1, 'active', 0, 'birth')
            """,
            (generation_id, subject_id),
        )
        await connection.execute(
            """
            INSERT INTO armi.parties (
                party_id, party_kind, represented_subject_id, creator_role
            ) VALUES
                (%s, 'subject', %s, NULL),
                (%s, 'creator', NULL, 'unique_primary_creator')
            """,
            (subject_party_id, subject_id, manifest.creator_party_id),
        )
        await connection.execute(
            """
            INSERT INTO armi.runtime_bundle_activations (
                bundle_activation_id, subject_id, bundle_version, bundle_digest,
                manifest_artifact_id, schema_baseline_digest,
                fixed_policy_digest, fixed_prompt_set_digest,
                creator_asset_digest, status, activated_by_party_id
            ) VALUES (
                %s, %s, '0.0.0', %s, %s, %s, %s, %s, %s, 'current', %s
            )
            """,
            (
                activation_id,
                subject_id,
                manifest.composition_digest.value,
                artifacts.activation_artifact_id,
                manifest.schema_manifest_digest.value,
                manifest.birth_contract_digest.value,
                artifacts.fixed_prompt_set_digest.value,
                manifest.creator_asset_manifest_digest.value,
                manifest.creator_party_id,
            ),
        )
        await connection.execute(
            """
            INSERT INTO armi.interaction_scenes (
                scene_id, subject_id, scene_key, scene_kind,
                primary_party_id, audience_scope, current_status, schema_version
            ) VALUES (
                %s, %s, 'default', 'creator_dialogue',
                %s, 'creator', 'open', 1
            )
            """,
            (default_scene_id, subject_id, manifest.creator_party_id),
        )
        await connection.execute(
            """
            INSERT INTO armi.prompt_documents (
                prompt_document_id, subject_id, prompt_kind,
                write_authority, current_revision_id
            ) VALUES
                (%s, %s, 'personality_anchor', 'fixed', %s),
                (%s, %s, 'creator_guidance', 'creator', NULL),
                (%s, %s, 'subject_guidance', 'subject', NULL)
            """,
            (
                anchor_document_id,
                subject_id,
                anchor_revision_id,
                creator_document_id,
                subject_id,
                subject_document_id,
                subject_id,
            ),
        )
        await connection.execute(
            """
            INSERT INTO armi.prompt_revisions (
                prompt_revision_id, prompt_document_id, revision_no,
                content_artifact_id, content_digest, author_party_id, change_reason
            ) VALUES (%s, %s, 1, %s, %s, %s, 'birth')
            """,
            (
                anchor_revision_id,
                anchor_document_id,
                artifacts.anchor_artifact_id,
                manifest.personality_anchor_digest.value,
                manifest.creator_party_id,
            ),
        )
        for kind, payload in (
            ("self", _SELF),
            ("mind", _MIND),
            ("life_mode", _LIFE_MODE),
        ):
            await connection.execute(
                """
                INSERT INTO armi.subject_component_revisions (
                    component_revision_id, subject_id, component_kind,
                    component_version, origin_kind, origin_ref,
                    semantic_payload, privacy_scope
                ) VALUES (%s, %s, %s, 1, 'bootstrap', %s, %s::jsonb, 'private')
                """,
                (
                    component_revisions[kind],
                    subject_id,
                    kind,
                    subject_id,
                    json.dumps(payload, sort_keys=True, separators=(",", ":")),
                ),
            )
            await connection.execute(
                """
                INSERT INTO armi.subject_component_heads (
                    subject_id, component_kind, current_revision_id,
                    component_version
                ) VALUES (%s, %s, %s, 1)
                """,
                (subject_id, kind, component_revisions[kind]),
            )
        return BirthResult(
            subject_id=subject_id,
            life_generation_id=generation_id,
            bundle_activation_id=activation_id,
            request_digest=manifest.request_digest,
            created=True,
        )


__all__ = (
    "BirthArtifacts",
    "BirthRepository",
    "ContinuityState",
    "probe_continuity",
)
