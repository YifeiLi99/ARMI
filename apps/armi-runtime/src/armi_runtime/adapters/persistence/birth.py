"""Package-private PostgreSQL write surface for the unique birth transaction."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import cast
from uuid import UUID, uuid7

import psycopg
from armi_cognition.api import FocusBirthPort
from armi_interaction.api import InteractionBirthPort
from armi_kernel.application import BirthManifest, BirthResult, BirthViolation
from armi_kernel.contracts import Digest
from armi_mind.api import MindBirthPort
from armi_mood.api import MoodBirthPort
from armi_prompt.api import (
    PromptBirthPort,
    PromptViolation,
)
from armi_runtime_foundation import (
    PostgreSQLAdminParameter,
    PostgreSQLAdminResult,
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
    interaction: InteractionBirthPort,
    subject_state: SubjectStateBirthPort,
    mind: MindBirthPort,
    focus: FocusBirthPort,
    mood: MoodBirthPort,
    prompts: PromptBirthPort,
) -> ContinuityState:
    try:
        with psycopg.connect(conninfo, autocommit=True) as connection:
            rows = connection.execute(
                """
                SELECT
                    subject.subject_id,
                    subject.birth_contract_digest
                FROM armi.subjects AS subject
                ORDER BY subject.singleton_key
                """
            ).fetchall()
            if not rows:
                interaction_counts = interaction.continuity(
                    _BirthAdminTransaction(connection), subject_id=None
                )
                transaction = _BirthAdminTransaction(connection)
                prompt_counts = prompts.continuity(transaction, subject_id=None)
                subject_counts = subject_state.continuity(transaction, subject_id=None)
                mood_counts = mood.continuity(transaction, subject_id=None)
                mind_counts = mind.continuity(transaction, subject_id=None)
                focus_counts = focus.continuity(transaction, subject_id=None)
                return (
                    ContinuityState.UNBORN
                    if interaction_counts.party_count == 0
                    and interaction_counts.default_scene_count == 0
                    and interaction_counts.timeline_count == 0
                    and prompt_counts.document_count == 0
                    and prompt_counts.revision_count == 0
                    and subject_counts.head_count == 0
                    and subject_counts.revision_count == 0
                    and mind_counts.head_count == 0
                    and mind_counts.revision_count == 0
                    and focus_counts.head_count == 0
                    and focus_counts.revision_count == 0
                    and mood_counts.head_count == 0
                    and mood_counts.revision_count == 0
                    else ContinuityState.INVALID
                )
            transaction = _BirthAdminTransaction(connection)
            interaction_counts = interaction.continuity(
                transaction, subject_id=rows[0][0]
            )
            prompt_counts = prompts.continuity(transaction, subject_id=rows[0][0])
            subject_counts = subject_state.continuity(
                transaction, subject_id=rows[0][0]
            )
            mood_counts = mood.continuity(transaction, subject_id=rows[0][0])
            mind_counts = mind.continuity(transaction, subject_id=rows[0][0])
            focus_counts = focus.continuity(transaction, subject_id=rows[0][0])
    except psycopg.Error, PromptViolation, RuntimeError:
        return ContinuityState.INVALID
    if len(rows) != 1:
        return ContinuityState.INVALID
    row = rows[0]
    if str(row[1]) != birth_contract_digest.value:
        return ContinuityState.INVALID
    if (
        interaction_counts.party_count != 2
        or prompt_counts.document_count != 1
        or prompt_counts.revision_count < 1
        or subject_counts.head_count != 2
        or subject_counts.revision_count < 2
        or mind_counts.head_count != 1
        or mind_counts.revision_count < 1
        or focus_counts.head_count != 1
        or focus_counts.revision_count < 1
        or mood_counts.head_count != 1
        or mood_counts.revision_count < 1
        or interaction_counts.default_scene_count != 1
    ):
        return ContinuityState.INVALID
    return ContinuityState.BORN


class _BirthAdminTransaction:
    __slots__ = ("_connection",)

    def __init__(self, connection: psycopg.Connection[tuple[object, ...]]) -> None:
        self._connection = connection

    def execute(
        self,
        statement: str,
        parameters: tuple[PostgreSQLAdminParameter, ...] = (),
    ) -> PostgreSQLAdminResult[tuple[object, ...]]:
        return cast(
            PostgreSQLAdminResult[tuple[object, ...]],
            self._connection.execute(  # pyright: ignore[reportArgumentType]
                statement,  # pyright: ignore[reportArgumentType]
                parameters,
            ),
        )


@dataclass(frozen=True, slots=True)
class BirthArtifacts:
    anchor_artifact_id: UUID
    anchor_content_digest: Digest


class BirthRepository:
    """Write all birth facts through the caller's active SERIALIZABLE UoW."""

    __slots__ = (
        "_focus",
        "_interaction",
        "_mind",
        "_mood",
        "_prompts",
        "_subject_state",
    )

    def __init__(
        self,
        subject_state: SubjectStateBirthPort,
        mind: MindBirthPort,
        focus: FocusBirthPort,
        mood: MoodBirthPort,
        prompts: PromptBirthPort,
        interaction: InteractionBirthPort,
    ) -> None:
        self._subject_state = subject_state
        self._mind = mind
        self._focus = focus
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
            row[2] == manifest.birth_request_id
            and str(row[3]) == manifest.idempotency_key
            and str(row[4]) == manifest.request_digest.value
        ):
            return BirthResult(
                subject_id=row[0],
                bundle_activation_id=row[1],
                request_digest=manifest.request_digest,
                created=False,
            )
        if str(row[3]) == manifest.idempotency_key:
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
        activation_id = uuid7()
        await connection.execute(
            """
            INSERT INTO armi.subjects (
                subject_id, singleton_key, birth_request_id,
                birth_idempotency_key, birth_manifest_digest, current_bundle_activation_id,
                birth_contract_digest, birth_creator_party_id
            ) VALUES (%s, 1, %s, %s, %s, %s, %s, %s)
            """,
            (
                subject_id,
                manifest.birth_request_id,
                manifest.idempotency_key,
                manifest.request_digest.value,
                activation_id,
                manifest.birth_contract_digest.value,
                manifest.creator_party_id,
            ),
        )
        await self._interaction.initialize(
            unit_of_work.transaction,
            subject_id=subject_id,
            creator_party_id=manifest.creator_party_id,
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
        await self._mind.initialize(unit_of_work.transaction, subject_id=subject_id)
        await self._focus.initialize(unit_of_work.transaction, subject_id=subject_id)
        await self._mood.initialize(unit_of_work.transaction, subject_id=subject_id)
        return BirthResult(
            subject_id=subject_id,
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
