"""Cognition-owned lifecycle for Context preparation episodes."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import cast
from uuid import UUID

from armi_experience.api import AcceptedExperienceSnapshot, ExperienceReadPort
from armi_kernel.application import CandidateViolation
from armi_kernel.contracts import Digest, TraceId
from armi_runtime_foundation import (
    PostgreSQLTransaction,
    cancel_cognition_work,
)

from .api import (
    CognitionContextEpisodeDraft,
    CognitionContextEpisodeSnapshot,
    CognitionExperienceContextItem,
    CognitionMaintenanceProgressPort,
)


class PostgreSQLCognitionContextLifecycle:
    __slots__ = ("_experiences", "_maintenance")

    def __init__(
        self,
        experiences: ExperienceReadPort,
        maintenance: CognitionMaintenanceProgressPort,
    ) -> None:
        self._experiences = experiences
        self._maintenance = maintenance

    async def active_opportunities(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> tuple[UUID, ...]:
        rows = await (
            await transaction.execute(
                """SELECT opportunity_id FROM armi.cognitive_episodes
               WHERE subject_id=%s AND status IN ('preparing','prepared','calling_model','finalizing')""",
                (subject_id,),
            )
        ).fetchall()
        return tuple(row[0] for row in rows)

    async def interrupt_autonomy(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
    ) -> tuple[UUID, ...]:
        rows = await (
            await transaction.execute(
                """UPDATE armi.cognitive_episodes SET status='cancelled',
                   failure_code='COGNITION-HUMAN-INPUT-PREEMPTED'
               WHERE subject_id=%s AND purpose IN
                   ('consider_autonomy_check','consider_autonomous_life')
                 AND status IN ('preparing','prepared','calling_model','finalizing')
               RETURNING cognitive_episode_id,opportunity_id""",
                (subject_id,),
            )
        ).fetchall()
        if not rows:
            return ()
        episodes = [row[0] for row in rows]
        await transaction.execute(
            """UPDATE armi.cognitive_attempts SET dispatch_status='settled',
                   result_status=CASE dispatch_status WHEN 'prepared' THEN 'cancelled'
                     ELSE 'outcome_unknown' END,
                   error_code='MODEL-HUMAN-INPUT-PREEMPTED',settled_at=statement_timestamp()
               WHERE cognitive_episode_id=ANY(%s::uuid[])
                 AND dispatch_status IN ('prepared','dispatched')""",
            (episodes,),
        )
        await cancel_cognition_work(transaction, episode_ids=tuple(episodes))
        return tuple(row[1] for row in rows)

    async def create_context_episode(
        self, transaction: PostgreSQLTransaction, draft: CognitionContextEpisodeDraft
    ) -> bool:
        row = await (
            await transaction.execute(
                """INSERT INTO armi.cognitive_episodes (
                   cognitive_episode_id, opportunity_id, subject_id, scene_id,
                   context_party_id, purpose, status, base_subject_version,
                   base_state_epoch, bundle_activation_id, mechanism_identity, trace_id)
               VALUES (%s,%s,%s,%s,%s,%s,'preparing',%s,%s,%s,%s,%s)
               ON CONFLICT (opportunity_id) DO NOTHING
               RETURNING cognitive_episode_id""",
                (
                    draft.episode_id,
                    draft.opportunity_id,
                    draft.subject_id,
                    draft.scene_id,
                    draft.context_party_id,
                    draft.purpose,
                    draft.base_subject_version,
                    draft.base_state_epoch,
                    draft.bundle_activation_id,
                    draft.mechanism_identity,
                    draft.trace_id.value,
                ),
            )
        ).fetchone()
        if row is not None and draft.purpose == "maintain_subjective_memory":
            if draft.maintenance_trigger_kind not in {"runtime_idle", "sleep"}:
                raise CandidateViolation("CANDIDATE-MAINTENANCE-TRIGGER")
            cursor = await self._maintenance.pending_window(
                transaction, subject_id=draft.subject_id
            )
            if cursor is not None:
                existing = await (
                    await transaction.execute(
                        """SELECT cognitive_episode_id
                           FROM armi.cognitive_episodes
                           WHERE subject_id=%s
                             AND maintenance_status='running'
                           FOR UPDATE""",
                        (draft.subject_id,),
                    )
                ).fetchone()
                if existing is None:
                    processed = int(cursor[1])
                    latest = int(cursor[0])
                    candidate_sources = (
                        await self._experiences.accepted_in_ordinal_window(
                            transaction,
                            subject_id=draft.subject_id,
                            after_ordinal=processed,
                            through_ordinal=latest,
                            limit=65,
                        )
                    )
                    sources = candidate_sources[:64]
                    frozen_through = (
                        sources[-1].acceptance_ordinal
                        if len(candidate_sources) == 65
                        else latest
                    )
                    source_episode_id = draft.episode_id
                    # The first episode owns the frozen scope for the whole
                    # maintenance sequence, including later reflections (DESIGN.md).
                    await transaction.execute(
                        """UPDATE armi.cognitive_episodes
                           SET maintenance_source_episode_id=cognitive_episode_id,
                               maintenance_trigger_kind=%s,maintenance_status='running',
                               maintenance_from_ordinal=%s,maintenance_through_ordinal=%s,
                               maintenance_experience_ids=%s::uuid[]
                           WHERE cognitive_episode_id=%s""",
                        (
                            draft.maintenance_trigger_kind,
                            processed,
                            frozen_through,
                            [item.experience_id.value for item in sources],
                            source_episode_id,
                        ),
                    )
                else:
                    source_episode_id = cast(UUID, existing[0])
                    await transaction.execute(
                        """UPDATE armi.cognitive_episodes SET maintenance_source_episode_id=%s
                           WHERE cognitive_episode_id=%s""",
                        (source_episode_id, draft.episode_id),
                    )
        elif row is not None and draft.purpose in {
            "reflect_self",
            "reflect_mind",
            "reflect_mood",
            "reflect_prompt",
        }:
            await transaction.execute(
                """UPDATE armi.cognitive_episodes AS episode
                   SET maintenance_source_episode_id=source.cognitive_episode_id
                   FROM armi.cognitive_episodes AS source
                   WHERE episode.cognitive_episode_id=%s
                     AND source.subject_id=%s
                     AND source.maintenance_status='running'""",
                (draft.episode_id, draft.subject_id),
            )
        return row is not None

    async def context_episode(
        self, transaction: PostgreSQLTransaction, *, episode_id: UUID
    ) -> CognitionContextEpisodeSnapshot:
        row = await (
            await transaction.execute(
                """SELECT cognitive_episode_id, opportunity_id, subject_id, scene_id,
                      context_party_id, purpose, base_subject_version,
                      base_state_epoch, bundle_activation_id, mechanism_identity,
                      trace_id
               FROM armi.cognitive_episodes
               WHERE cognitive_episode_id=%s AND status='preparing'""",
                (episode_id,),
            )
        ).fetchone()
        if row is None:
            raise CandidateViolation("CANDIDATE-EPISODE-STATE")
        life = await (
            await transaction.execute(
                """SELECT exact_life_query_intent_id, life_query_result_artifact_id
               FROM armi.cognitive_episodes
               WHERE life_query_result_opportunity_id=%s""",
                (row[1],),
            )
        ).fetchone()
        experiences: tuple[CognitionExperienceContextItem, ...] = ()
        purpose = str(row[5])
        if purpose == "maintain_subjective_memory":
            source_rows = await (
                await transaction.execute(
                    """SELECT source.experience_id,source.ordinal
                       FROM armi.cognitive_episodes AS episode
                       JOIN armi.cognitive_episodes AS root
                         ON root.cognitive_episode_id=episode.maintenance_source_episode_id
                       CROSS JOIN LATERAL unnest(root.maintenance_experience_ids)
                         WITH ORDINALITY AS source(experience_id,ordinal)
                       WHERE episode.cognitive_episode_id=%s
                         AND root.maintenance_status='running'
                       ORDER BY source.ordinal""",
                    (episode_id,),
                )
            ).fetchall()
            snapshots = await self._experiences.by_ids(
                transaction,
                subject_id=cast(UUID, row[2]),
                experience_ids=tuple(cast(UUID, item[0]) for item in source_rows),
            )
            experiences = _experience_context(
                snapshots,
                ordinals=tuple(cast(int, item[1]) for item in source_rows),
                maintenance_source=True,
            )
        elif purpose in {
            "consider_creator_input",
            "consider_creator_voice_input",
            "consider_life_query_result",
        }:
            snapshots = await self._experiences.recent(
                transaction,
                subject_id=cast(UUID, row[2]),
                limit=8,
            )
            experiences = _experience_context(
                snapshots,
                ordinals=tuple(range(len(snapshots), 0, -1)),
                maintenance_source=False,
            )
        return _snapshot(row, life, experiences)

    async def mark_context_prepared(
        self,
        transaction: PostgreSQLTransaction,
        *,
        episode_id: UUID,
        manifest_artifact_id: UUID,
        compiled_artifact_id: UUID,
        compiled_digest: Digest,
        context_items: tuple[dict[str, object], ...],
    ) -> CognitionContextEpisodeSnapshot:
        _validate_context_items(context_items)
        row = await (
            await transaction.execute(
                """UPDATE armi.cognitive_episodes SET status='prepared',
                      context_manifest_artifact_id=%s,
                      compiled_context_artifact_id=%s,
                      compiled_context_digest=%s,
                      context_items=%s::jsonb, prepared_at=statement_timestamp()
               WHERE cognitive_episode_id=%s AND status='preparing'
               RETURNING cognitive_episode_id, opportunity_id, subject_id, scene_id,
                         context_party_id, purpose, base_subject_version,
                         base_state_epoch, bundle_activation_id, mechanism_identity,
                         trace_id""",
                (
                    manifest_artifact_id,
                    compiled_artifact_id,
                    compiled_digest.value,
                    json.dumps(context_items),
                    episode_id,
                ),
            )
        ).fetchone()
        if row is None:
            raise CandidateViolation("CANDIDATE-EPISODE-STATE")
        return _snapshot(row, None)

    async def fail_context(
        self,
        transaction: PostgreSQLTransaction,
        *,
        episode_id: UUID,
        error_code: str,
    ) -> CognitionContextEpisodeSnapshot:
        row = await (
            await transaction.execute(
                """UPDATE armi.cognitive_episodes SET status='failed', failure_code=%s
               WHERE cognitive_episode_id=%s AND status='preparing'
               RETURNING cognitive_episode_id, opportunity_id, subject_id, scene_id,
                         context_party_id, purpose, base_subject_version,
                         base_state_epoch, bundle_activation_id, mechanism_identity,
                         trace_id""",
                (error_code, episode_id),
            )
        ).fetchone()
        if row is None:
            raise CandidateViolation("CANDIDATE-EPISODE-STATE")
        return _snapshot(row, None)


def _snapshot(
    row: tuple[object, ...],
    life: tuple[object, ...] | None,
    experiences: tuple[CognitionExperienceContextItem, ...] = (),
) -> CognitionContextEpisodeSnapshot:
    return CognitionContextEpisodeSnapshot(
        episode_id=cast(UUID, row[0]),
        opportunity_id=cast(UUID, row[1]),
        subject_id=cast(UUID, row[2]),
        scene_id=cast(UUID | None, row[3]),
        context_party_id=cast(UUID | None, row[4]),
        purpose=str(row[5]),
        base_subject_version=cast(int, row[6]),
        base_state_epoch=cast(int, row[7]),
        bundle_activation_id=cast(UUID, row[8]),
        mechanism_identity=str(row[9]),
        trace_id=TraceId(str(row[10])),
        life_query_intent_id=None if life is None else cast(UUID, life[0]),
        life_query_result_artifact_id=None if life is None else cast(UUID, life[1]),
        experience_context=experiences,
    )


def _experience_context(
    snapshots: Sequence[AcceptedExperienceSnapshot],
    *,
    ordinals: tuple[int, ...],
    maintenance_source: bool,
) -> tuple[CognitionExperienceContextItem, ...]:
    return tuple(
        CognitionExperienceContextItem(
            experience_id=snapshot.experience_id.value,
            ordinal=ordinal,
            fact_class=snapshot.fact_class.value,
            first_person_gist=snapshot.first_person_gist,
            occurred_at=snapshot.occurred_at,
            accepted_at=snapshot.accepted_at,
            source_perspective=snapshot.source_perspective.value,
            uncertainty=snapshot.uncertainty,
            maintenance_source=maintenance_source,
        )
        for snapshot, ordinal in zip(snapshots, ordinals, strict=True)
    )


async def autonomy_check_current(
    transaction: PostgreSQLTransaction,
    *,
    root_opportunity_id: UUID,
    subject_version: int,
    state_epoch: int,
    bundle_activation_id: UUID,
    last_input_at: object,
) -> bool:
    row = await (
        await transaction.execute(
            """SELECT base_subject_version,base_state_epoch,bundle_activation_id,created_at
           FROM armi.cognitive_episodes WHERE opportunity_id=%s
             AND purpose='consider_autonomy_check' AND status='completed'""",
            (root_opportunity_id,),
        )
    ).fetchone()
    return (
        row is not None
        and tuple(row[:3]) == (subject_version, state_epoch, bundle_activation_id)
        and (last_input_at is None or row[3] >= last_input_at)
    )


__all__ = ("PostgreSQLCognitionContextLifecycle",)


def _validate_context_items(items: tuple[dict[str, object], ...]) -> None:
    # Frozen reference identity stays unique after embedding the list; see DESIGN.md.
    identifiers: set[UUID] = set()
    ordinals: set[int] = set()
    fields = {
        "context_item_id",
        "ordinal",
        "section",
        "item_kind",
        "source_kind",
        "source_ref",
        "source_version",
        "trust_class",
        "privacy_scope",
        "disposition",
        "reason_code",
        "content_bytes",
    }
    for item in items:
        try:
            identity = UUID(str(item["context_item_id"]))
            ordinal = item["ordinal"]
            source_ref = item["source_ref"]
            source_version = item["source_version"]
            disposition = item["disposition"]
            reason = item["reason_code"]
            size = item["content_bytes"]
            if (
                set(item) != fields
                or identity.version != 7
                or identity in identifiers
                or type(ordinal) is not int
                or not 1 <= ordinal <= 32767
                or ordinal in ordinals
                or item["section"]
                not in {
                    "runtime_truth",
                    "purpose",
                    "self",
                    "mind",
                    "mood",
                    "life_mode",
                    "scene",
                    "relationship",
                    "memory",
                    "activity",
                    "material",
                    "evidence",
                    "capability",
                    "prompt",
                }
                or any(
                    re.fullmatch(r"[a-z][a-z0-9._-]{0,63}", str(item[field])) is None
                    for field in ("item_kind", "source_kind")
                )
                or (source_ref is None) != (source_version is None)
                or (
                    source_ref is not None
                    and (
                        UUID(str(source_ref)).version != 7
                        or type(source_version) is not int
                        or source_version < 0
                    )
                )
                or item["trust_class"]
                not in {
                    "runtime_authority",
                    "subjective_state",
                    "external_claim",
                    "policy",
                }
                or item["privacy_scope"] not in {"internal", "private", "restricted"}
                or disposition
                not in {
                    "included",
                    "excluded_policy",
                    "excluded_budget",
                    "unavailable",
                    "read_failed",
                }
                or (
                    (disposition in {"included", "excluded_policy"}) != (reason is None)
                )
                or (
                    reason is not None
                    and re.fullmatch(r"CTX-[A-Z0-9-]+", str(reason)) is None
                )
                or type(size) is not int
                or size < 0
            ):
                raise ValueError("invalid frozen Context item")
        except (KeyError, ValueError, TypeError) as error:
            raise CandidateViolation("CANDIDATE-CONTEXT-ITEMS") from error
        identifiers.add(identity)
        ordinals.add(ordinal)
