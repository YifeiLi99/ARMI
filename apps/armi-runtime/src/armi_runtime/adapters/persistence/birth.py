"""Package-private PostgreSQL write surface for the unique birth transaction."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID, uuid7

import psycopg
from armi_interaction.api import InteractionBirthPort
from armi_kernel.application import BirthManifest, BirthResult, BirthViolation
from armi_kernel.contracts import Digest
from armi_mood.api import MoodBirthPort
from armi_prompt.api import (
    PromptBirthPort,
    PromptViolation,
    probe_prompt_continuity,
)
from armi_subject_state.api import SubjectStateBirthPort

from .unit_of_work import PostgreSQLUnitOfWork


class ContinuityState(StrEnum):
    UNBORN = "unborn"
    BORN = "born"
    INVALID = "invalid"


def probe_continuity(
    conninfo: str,
    *,
    birth_contract_digest: Digest,
) -> ContinuityState:
    try:
        with psycopg.connect(conninfo, autocommit=True) as connection:
            rows = connection.execute(
                """
                SELECT
                    subject.subject_id,
                    activation.fixed_policy_digest,
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
                    0::bigint,
                    0::bigint,
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
                      + 0
                      + (SELECT count(*) FROM armi.interaction_scenes)
                      + (SELECT count(*) FROM armi.scene_timeline_items)
                    """
                ).fetchone()
                prompt_counts = probe_prompt_continuity(conninfo, subject_id=None)
                return (
                    ContinuityState.UNBORN
                    if counts is not None
                    and counts[0] == 0
                    and prompt_counts.document_count == 0
                    and prompt_counts.revision_count == 0
                    else ContinuityState.INVALID
                )
    except psycopg.Error, PromptViolation:
        return ContinuityState.INVALID
    if len(rows) != 1:
        return ContinuityState.INVALID
    row = rows[0]
    if str(row[1]) != birth_contract_digest.value:
        return ContinuityState.INVALID
    try:
        prompt_counts = probe_prompt_continuity(conninfo, subject_id=row[0])
    except PromptViolation:
        return ContinuityState.INVALID
    counts = tuple(int(value) for value in row[2:])
    if (
        counts[0:2] != (1, 2)
        or prompt_counts.document_count != 3
        or prompt_counts.revision_count < 1
        or counts[4] != 1
    ):
        return ContinuityState.INVALID
    return ContinuityState.BORN


@dataclass(frozen=True, slots=True)
class BirthArtifacts:
    anchor_artifact_id: UUID
    anchor_content_digest: Digest


class BirthRepository:
    """Write all birth facts through the caller's active SERIALIZABLE UoW."""

    __slots__ = ("_interaction", "_mood", "_prompts", "_subject_state")

    def __init__(
        self,
        subject_state: SubjectStateBirthPort,
        mood: MoodBirthPort,
        prompts: PromptBirthPort,
        interaction: InteractionBirthPort,
    ) -> None:
        self._subject_state = subject_state
        self._prompts = prompts
        self._mood = mood
        self._interaction = interaction

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
        await self._interaction.initialize(
            unit_of_work.transaction,
            subject_id=subject_id,
            creator_party_id=manifest.creator_party_id,
        )
        await connection.execute(
            """
            INSERT INTO armi.runtime_bundle_activations (
                bundle_activation_id, subject_id, bundle_version,
                fixed_policy_digest,
                status, activated_by_party_id
            ) VALUES (
                %s, %s, '0.0.0', %s, 'current', %s
            )
            """,
            (
                activation_id,
                subject_id,
                manifest.birth_contract_digest.value,
                manifest.creator_party_id,
            ),
        )
        await self._prompts.initialize(
            unit_of_work.transaction,
            subject_id=subject_id,
            creator_party_id=manifest.creator_party_id,
            anchor_artifact_id=artifacts.anchor_artifact_id,
            anchor_content_digest=artifacts.anchor_content_digest,
        )
        await self._subject_state.initialize(
            unit_of_work.transaction, subject_id=subject_id
        )
        await self._mood.initialize(unit_of_work.transaction, subject_id=subject_id)
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
