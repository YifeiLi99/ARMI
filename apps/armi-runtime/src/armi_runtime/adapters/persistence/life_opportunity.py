"""PostgreSQL ownership for autonomous life opportunity admission."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import uuid7

from armi_kernel.application import (
    ActivityHeadSnapshot,
    ActivityStatus,
    ActivityWaitingKind,
    AuditDraft,
    AuditEventId,
    AuditReference,
    AuditResultStatus,
    AuditSensitivity,
    CreatorOutreachPolicy,
    LifeOpportunitySourceKind,
    LifeSchedulingDisposition,
    LifeSchedulingSnapshot,
    LifeViolation,
    OpportunityAdmissionOutcome,
    OpportunityAdmissionStatus,
    PostgreSqlFairLifeScheduler,
)
from armi_kernel.contracts import (
    ActivityId,
    ContractViolation,
    Purpose,
    SubjectId,
    TraceId,
)
from armi_relationship.api import RelationshipPolicyPort, RelationshipReadPort
from armi_sleep.api import SleepReadPort

from .unit_of_work import PostgreSQLUnitOfWork


class PostgreSQLLifeOpportunityRepository:
    """Admit one source-backed root opportunity under the active Runtime fence."""

    __slots__ = ("_relationship_policy", "_relationships", "_sleep")

    def __init__(
        self,
        relationships: RelationshipReadPort,
        relationship_policy: RelationshipPolicyPort,
        sleep: SleepReadPort,
    ) -> None:
        self._relationships = relationships
        self._relationship_policy = relationship_policy
        self._sleep = sleep

    async def admit_generation_available(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
    ) -> OpportunityAdmissionOutcome:
        fence = unit_of_work.runtime_fence
        if fence is None:
            raise LifeViolation("LIFE-FENCE-REQUIRED")
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        row = await (
            await connection.execute(
                """
                SELECT generation_no, activation_reason
                FROM armi.life_generations
                WHERE life_generation_id = %s
                  AND subject_id = %s
                  AND status = 'active'
                """,
                (fence.life_generation_id, fence.subject_id),
            )
        ).fetchone()
        if row is None:
            raise LifeViolation("LIFE-SOURCE-STALE")
        opportunity_id = uuid7()
        inserted = await (
            await connection.execute(
                """
                INSERT INTO armi.opportunities (
                    opportunity_id, evidence_id, subject_id, scene_id,
                    context_party_id, purpose, eligibility_status,
                    current_disposition, root_opportunity_id,
                    reconsideration_no, source_kind, source_ref,
                    source_version)
                VALUES (
                    %s, NULL, %s, NULL, NULL, 'consider_autonomous_life',
                    'eligible', 'open', %s, 0,
                    'life_generation_available', %s, %s)
                ON CONFLICT (
                    subject_id, source_kind, source_ref, source_version,
                    purpose, reconsideration_no
                ) DO NOTHING
                RETURNING opportunity_id
                """,
                (
                    opportunity_id,
                    fence.subject_id,
                    opportunity_id,
                    fence.life_generation_id,
                    int(row[0]),
                ),
            )
        ).fetchone()
        if inserted is None:
            existing = await (
                await connection.execute(
                    """
                    SELECT opportunity_id
                    FROM armi.opportunities
                    WHERE subject_id = %s
                      AND source_kind = 'life_generation_available'
                      AND source_ref = %s
                      AND source_version = %s
                      AND purpose = 'consider_autonomous_life'
                      AND reconsideration_no = 0
                    """,
                    (fence.subject_id, fence.life_generation_id, int(row[0])),
                )
            ).fetchone()
            if existing is None:
                raise LifeViolation("LIFE-SOURCE-STALE")
            return OpportunityAdmissionOutcome(
                OpportunityAdmissionStatus.DUPLICATE,
                existing[0],
            )
        trace_id = TraceId(opportunity_id.hex)
        await unit_of_work.audit.append(
            AuditDraft(
                AuditEventId(uuid7()),
                AuditReference("runtime", unit_of_work.environment_id),
                Purpose("life.opportunity"),
                "life.opportunity.admitted",
                AuditReference("opportunity", opportunity_id),
                AuditResultStatus.APPLIED,
                trace_id,
                AuditSensitivity.PRIVATE,
                subject_id=SubjectId(fence.subject_id),
                request=AuditReference("life_generation", fence.life_generation_id),
            )
        )
        return OpportunityAdmissionOutcome(
            OpportunityAdmissionStatus.ADMITTED,
            opportunity_id,
        )

    async def admit_life_material_revision(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
    ) -> OpportunityAdmissionOutcome:
        """Offer one current active ARMI-owned material for autonomous consideration."""

        fence = unit_of_work.runtime_fence
        if fence is None:
            raise LifeViolation("LIFE-FENCE-REQUIRED")
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        row = await (
            await connection.execute(
                """
                SELECT material.life_material_id,
                       revision.life_material_revision_id,
                       material.head_version
                FROM armi.life_materials AS material
                JOIN armi.life_material_revisions AS revision
                  ON revision.life_material_revision_id =
                     material.current_revision_id
                WHERE material.subject_id = %s
                  AND material.life_generation_id = %s
                  AND material.deleted_at IS NULL
                  AND revision.material_status = 'active'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM armi.opportunities AS existing
                      WHERE existing.subject_id = material.subject_id
                        AND existing.source_kind = 'life_material_revision'
                        AND existing.source_ref =
                            revision.life_material_revision_id
                        AND existing.source_version = material.head_version
                        AND existing.purpose = 'consider_autonomous_life'
                        AND existing.reconsideration_no = 0
                  )
                ORDER BY material.updated_at, material.life_material_id
                LIMIT 1
                """,
                (fence.subject_id, fence.life_generation_id),
            )
        ).fetchone()
        if row is None:
            return OpportunityAdmissionOutcome(
                OpportunityAdmissionStatus.REJECTED,
                None,
                "LIFE-MATERIAL-IDLE",
            )
        opportunity_id = uuid7()
        inserted = await (
            await connection.execute(
                """
                INSERT INTO armi.opportunities (
                    opportunity_id, evidence_id, subject_id, scene_id,
                    context_party_id, purpose, eligibility_status,
                    current_disposition, root_opportunity_id,
                    reconsideration_no, source_kind, source_ref,
                    source_version) VALUES (
                    %s, NULL, %s, NULL, NULL, 'consider_autonomous_life',
                    'eligible', 'open', %s, 0, 'life_material_revision',
                    %s, %s)
                ON CONFLICT (
                    subject_id, source_kind, source_ref, source_version,
                    purpose, reconsideration_no
                ) DO NOTHING RETURNING opportunity_id
                """,
                (
                    opportunity_id,
                    fence.subject_id,
                    opportunity_id,
                    row[1],
                    int(row[2]),
                ),
            )
        ).fetchone()
        if inserted is None:
            existing = await (
                await connection.execute(
                    """
                    SELECT opportunity_id
                    FROM armi.opportunities
                    WHERE subject_id = %s
                      AND source_kind = 'life_material_revision'
                      AND source_ref = %s
                      AND source_version = %s
                      AND purpose = 'consider_autonomous_life'
                      AND reconsideration_no = 0
                    """,
                    (fence.subject_id, row[1], int(row[2])),
                )
            ).fetchone()
            if existing is None:
                raise LifeViolation("LIFE-SOURCE-STALE")
            return OpportunityAdmissionOutcome(
                OpportunityAdmissionStatus.DUPLICATE,
                existing[0],
            )
        await unit_of_work.audit.append(
            AuditDraft(
                AuditEventId(uuid7()),
                AuditReference("runtime", unit_of_work.environment_id),
                Purpose("life.opportunity"),
                "life.opportunity.admitted",
                AuditReference("opportunity", opportunity_id),
                AuditResultStatus.APPLIED,
                TraceId(opportunity_id.hex),
                AuditSensitivity.PRIVATE,
                subject_id=SubjectId(fence.subject_id),
                request=AuditReference("life_material_revision", row[1]),
            )
        )
        return OpportunityAdmissionOutcome(
            OpportunityAdmissionStatus.ADMITTED,
            opportunity_id,
        )

    async def admit_activity_attention(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        *,
        model_concurrency: int,
    ) -> OpportunityAdmissionOutcome:
        fence = unit_of_work.runtime_fence
        if fence is None:
            raise LifeViolation("LIFE-FENCE-REQUIRED")
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        maintenance = await self._sleep.active_maintenance(
            connection, subject_id=fence.subject_id
        )
        state = await (
            await connection.execute(
                """
                SELECT revision.semantic_payload,
                       EXISTS (
                           SELECT 1 FROM armi.opportunities
                           WHERE subject_id = %s
                             AND purpose = 'consider_activity_attention'
                             AND current_disposition IN ('open', 'selected')
                       ),
                       (SELECT count(*) FROM armi.cognitive_episodes
                        WHERE status NOT IN (
                            'completed', 'stale', 'failed', 'cancelled',
                            'candidate_rejected'
                        ))
                FROM armi.subject_component_heads AS head
                JOIN armi.subject_component_revisions AS revision
                  ON revision.component_revision_id = head.current_revision_id
                WHERE head.subject_id = %s AND head.component_kind = 'life_mode'
                """,
                (fence.subject_id, fence.subject_id),
            )
        ).fetchone()
        if state is None or not isinstance(state[0], dict):
            raise LifeViolation("LIFE-SCHEDULER-STATE")
        if maintenance is not None:
            return OpportunityAdmissionOutcome(
                OpportunityAdmissionStatus.REJECTED,
                None,
                "LIFE-BACKPRESSURE-MAINTENANCE",
            )
        life_mode = cast(dict[str, object], state[0])
        active_values = life_mode.get("active_activities")
        if type(active_values) is not list:
            raise LifeViolation("LIFE-SCHEDULER-FOCUS")
        active_list = cast(list[object], active_values)
        if len(active_list) > 1:
            raise LifeViolation("LIFE-SCHEDULER-FOCUS")
        try:
            active_ids = tuple(ActivityId.from_wire(value) for value in active_list)
        except ContractViolation:
            raise LifeViolation("LIFE-SCHEDULER-FOCUS") from None
        rows = await (
            await connection.execute(
                """
                SELECT activity.activity_id, revision.activity_revision_id,
                       revision.revision_no, revision.status, revision.created_at,
                       max(previous.available_after) AS last_considered_at,
                       revision.waiting_condition_kind,
                       revision.resume_not_before,
                       CASE
                         WHEN revision.waiting_condition_kind = 'creator_input' THEN EXISTS (
                           SELECT 1 FROM armi.party_input_interactions AS input
                           WHERE input.received_at > revision.created_at
                         )
                         WHEN revision.waiting_condition_kind = 'external_evidence' THEN EXISTS (
                           SELECT 1 FROM armi.external_evidence AS evidence
                           WHERE evidence.subject_id = activity.subject_id
                             AND evidence.received_at > revision.created_at
                         )
                         ELSE false
                       END AS waiting_signal_available,
                       revision.goal, revision.progress_summary,
                       revision.next_safe_step, revision.resumption_cue,
                       revision.terminal_reason
                FROM armi.activities AS activity
                JOIN armi.activity_revisions AS revision
                  ON revision.activity_revision_id = activity.current_revision_id
                LEFT JOIN armi.opportunities AS previous
                  ON previous.source_kind = 'activity_revision'
                 AND previous.source_ref = revision.activity_revision_id
                 AND previous.purpose = 'consider_activity_attention'
                WHERE activity.subject_id = %s
                  AND (
                    NOT EXISTS (
                        SELECT 1 FROM armi.opportunities AS candidate_root
                        WHERE candidate_root.subject_id = activity.subject_id
                          AND candidate_root.source_kind = 'activity_revision'
                          AND candidate_root.source_ref = revision.activity_revision_id
                          AND candidate_root.source_version = revision.revision_no
                          AND candidate_root.purpose = 'consider_activity_attention'
                          AND candidate_root.reconsideration_no = 0
                    )
                    OR EXISTS (
                        SELECT 1
                        FROM armi.opportunities AS candidate_root
                        WHERE candidate_root.subject_id = activity.subject_id
                          AND candidate_root.source_kind = 'activity_revision'
                          AND candidate_root.source_ref = revision.activity_revision_id
                          AND candidate_root.source_version = revision.revision_no
                          AND candidate_root.purpose = 'consider_activity_attention'
                          AND candidate_root.reconsideration_no = 0
                          AND candidate_root.current_disposition = 'resolved'
                          AND (
                            EXISTS (
                              SELECT 1 FROM armi.cognitive_episodes AS failed_episode
                              WHERE failed_episode.opportunity_id =
                                    candidate_root.opportunity_id
                                AND failed_episode.status IN (
                                    'failed', 'candidate_rejected'
                                )
                                AND candidate_root.resolved_at + interval '60 seconds'
                                    <= statement_timestamp()
                            )
                            OR EXISTS (
                              SELECT 1
                              FROM armi.cognitive_episodes AS waiting_episode
                              JOIN armi.activity_decisions AS decision
                                USING (cognitive_episode_id)
                              WHERE waiting_episode.opportunity_id =
                                    candidate_root.opportunity_id
                                AND waiting_episode.status = 'completed'
                                AND decision.decision_kind = 'need_information'
                                AND EXISTS (
                                  SELECT 1 FROM armi.party_input_interactions AS input
                                  WHERE input.received_at > decision.decided_at
                                )
                            )
                          )
                          AND NOT EXISTS (
                              SELECT 1
                              FROM armi.opportunities AS candidate_successor
                              WHERE candidate_successor.predecessor_opportunity_id =
                                    candidate_root.opportunity_id
                          )
                    )
                  )
                GROUP BY activity.activity_id, revision.activity_revision_id
                """,
                (fence.subject_id,),
            )
        ).fetchall()
        heads = tuple(
            ActivityHeadSnapshot(
                ActivityId(row[0]),
                row[1],
                int(row[2]),
                ActivityStatus(str(row[3])),
                row[4],
                row[5],
                None if row[6] is None else ActivityWaitingKind(str(row[6])),
                row[7],
                bool(row[8]),
            )
            for row in rows
        )
        decision = PostgreSqlFairLifeScheduler().select(
            LifeSchedulingSnapshot(
                datetime.now(UTC),
                heads,
                active_ids,
                bool(state[1]),
                model_concurrency,
                int(state[2]),
            )
        )
        if decision.disposition is not LifeSchedulingDisposition.ADMIT:
            return OpportunityAdmissionOutcome(
                OpportunityAdmissionStatus.REJECTED,
                None,
                decision.reason_code or "LIFE-SCHEDULER-IDLE",
            )
        selected = next(row for row in rows if row[1] == decision.activity_revision_id)
        opportunity_id = uuid7()
        inserted = await (
            await connection.execute(
                """
                INSERT INTO armi.opportunities (
                    opportunity_id, evidence_id, subject_id, scene_id,
                    context_party_id, purpose, eligibility_status,
                    current_disposition, root_opportunity_id,
                    reconsideration_no, source_kind, source_ref,
                    source_version, activity_id) VALUES (
                    %s, NULL, %s, NULL, NULL, 'consider_activity_attention',
                    'eligible', 'open', %s, 0, 'activity_revision',
                    %s, %s, %s)
                ON CONFLICT (
                    subject_id, source_kind, source_ref, source_version,
                    purpose, reconsideration_no
                ) DO NOTHING RETURNING opportunity_id
                """,
                (
                    opportunity_id,
                    fence.subject_id,
                    opportunity_id,
                    selected[1],
                    int(selected[2]),
                    selected[0],
                ),
            )
        ).fetchone()
        if inserted is None:
            existing = await (
                await connection.execute(
                    """
                    SELECT root.opportunity_id, root.current_disposition,
                           (
                             EXISTS (
                               SELECT 1 FROM armi.cognitive_episodes AS failed_episode
                               WHERE failed_episode.opportunity_id = root.opportunity_id
                                 AND failed_episode.status IN (
                                     'failed', 'candidate_rejected'
                                 )
                                 AND root.resolved_at + interval '60 seconds'
                                     <= statement_timestamp()
                             )
                             OR EXISTS (
                               SELECT 1
                               FROM armi.cognitive_episodes AS waiting_episode
                               JOIN armi.activity_decisions AS decision
                                 USING (cognitive_episode_id)
                               WHERE waiting_episode.opportunity_id = root.opportunity_id
                                 AND waiting_episode.status = 'completed'
                                 AND decision.decision_kind = 'need_information'
                                 AND EXISTS (
                                   SELECT 1 FROM armi.party_input_interactions AS input
                                   WHERE input.received_at > decision.decided_at
                                 )
                             )
                           ),
                           successor.opportunity_id
                    FROM armi.opportunities AS root
                    LEFT JOIN armi.opportunities AS successor
                      ON successor.predecessor_opportunity_id = root.opportunity_id
                    WHERE root.subject_id = %s
                      AND root.source_kind = 'activity_revision'
                      AND root.source_ref = %s AND root.source_version = %s
                      AND root.purpose = 'consider_activity_attention'
                      AND root.reconsideration_no = 0
                    """,
                    (fence.subject_id, selected[1], int(selected[2])),
                )
            ).fetchone()
            if existing is None:
                raise LifeViolation("LIFE-SOURCE-STALE")
            if existing[3] is not None:
                return OpportunityAdmissionOutcome(
                    OpportunityAdmissionStatus.DUPLICATE, existing[3]
                )
            if str(existing[1]) == "resolved" and bool(existing[2]):
                retry_id = uuid7()
                retried = await (
                    await connection.execute(
                        """
                        INSERT INTO armi.opportunities (
                            opportunity_id, evidence_id, subject_id, scene_id,
                            context_party_id, purpose, eligibility_status,
                            current_disposition, root_opportunity_id,
                            predecessor_opportunity_id, reconsideration_no,
                            source_kind, source_ref, source_version,
                            activity_id) VALUES (
                            %s, NULL, %s, NULL, NULL,
                            'consider_activity_attention', 'eligible', 'open',
                            %s, %s, 1, 'activity_revision', %s, %s, %s)
                        ON CONFLICT (predecessor_opportunity_id) DO NOTHING
                        RETURNING opportunity_id
                        """,
                        (
                            retry_id,
                            fence.subject_id,
                            existing[0],
                            existing[0],
                            selected[1],
                            int(selected[2]),
                            selected[0],
                        ),
                    )
                ).fetchone()
                if retried is not None:
                    await unit_of_work.audit.append(
                        AuditDraft(
                            AuditEventId(uuid7()),
                            AuditReference("runtime", unit_of_work.environment_id),
                            Purpose("life.attention.opportunity"),
                            "life.attention.opportunity.readmitted",
                            AuditReference("opportunity", retry_id),
                            AuditResultStatus.APPLIED,
                            TraceId(retry_id.hex),
                            AuditSensitivity.PRIVATE,
                            subject_id=SubjectId(fence.subject_id),
                            request=AuditReference("activity_revision", selected[1]),
                        )
                    )
                    return OpportunityAdmissionOutcome(
                        OpportunityAdmissionStatus.ADMITTED, retry_id
                    )
            return OpportunityAdmissionOutcome(
                OpportunityAdmissionStatus.DUPLICATE, existing[0]
            )
        await unit_of_work.audit.append(
            AuditDraft(
                AuditEventId(uuid7()),
                AuditReference("runtime", unit_of_work.environment_id),
                Purpose("life.attention.opportunity"),
                "life.attention.opportunity.admitted",
                AuditReference("opportunity", opportunity_id),
                AuditResultStatus.APPLIED,
                TraceId(opportunity_id.hex),
                AuditSensitivity.PRIVATE,
                subject_id=SubjectId(fence.subject_id),
                request=AuditReference("activity_revision", selected[1]),
            )
        )
        return OpportunityAdmissionOutcome(
            OpportunityAdmissionStatus.ADMITTED, opportunity_id
        )

    async def admit_activity_internal_work(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        *,
        model_concurrency: int,
    ) -> OpportunityAdmissionOutcome:
        """Admit one bounded work step for the Activity holding attention."""

        fence = unit_of_work.runtime_fence
        if fence is None:
            raise LifeViolation("LIFE-FENCE-REQUIRED")
        if model_concurrency < 2:
            return OpportunityAdmissionOutcome(
                OpportunityAdmissionStatus.REJECTED,
                None,
                "LIFE-BACKPRESSURE-MODEL-CONCURRENCY",
            )
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        maintenance = await self._sleep.active_maintenance(
            connection, subject_id=fence.subject_id
        )
        state = await (
            await connection.execute(
                """
                SELECT revision.semantic_payload,
                       EXISTS (
                           SELECT 1 FROM armi.opportunities
                           WHERE subject_id = %s
                             AND purpose = 'consider_activity_internal_work'
                             AND current_disposition IN ('open', 'selected')
                       ),
                       (SELECT count(*) FROM armi.cognitive_episodes
                        WHERE status NOT IN (
                            'completed', 'stale', 'failed', 'cancelled',
                            'candidate_rejected'
                        ))
                FROM armi.subject_component_heads AS head
                JOIN armi.subject_component_revisions AS revision
                  ON revision.component_revision_id = head.current_revision_id
                WHERE head.subject_id = %s AND head.component_kind = 'life_mode'
                """,
                (fence.subject_id, fence.subject_id),
            )
        ).fetchone()
        if state is None or not isinstance(state[0], dict):
            raise LifeViolation("LIFE-SCHEDULER-STATE")
        if maintenance is not None:
            return OpportunityAdmissionOutcome(
                OpportunityAdmissionStatus.REJECTED,
                None,
                "LIFE-BACKPRESSURE-MAINTENANCE",
            )
        if bool(state[1]):
            return OpportunityAdmissionOutcome(
                OpportunityAdmissionStatus.REJECTED,
                None,
                "LIFE-BACKPRESSURE-INTERNAL-WORK-OUTSTANDING",
            )
        if int(state[2]) >= model_concurrency - 1:
            return OpportunityAdmissionOutcome(
                OpportunityAdmissionStatus.REJECTED,
                None,
                "LIFE-BACKPRESSURE-COGNITION-CAPACITY",
            )
        active_values = cast(dict[str, object], state[0]).get("active_activities")
        if type(active_values) is not list:
            raise LifeViolation("LIFE-SCHEDULER-FOCUS")
        active_list = cast(list[object], active_values)
        if len(active_list) != 1:
            return OpportunityAdmissionOutcome(
                OpportunityAdmissionStatus.REJECTED,
                None,
                "LIFE-SCHEDULER-IDLE",
            )
        try:
            activity_id = ActivityId.from_wire(active_list[0])
        except ContractViolation:
            raise LifeViolation("LIFE-SCHEDULER-FOCUS") from None
        row = await (
            await connection.execute(
                """
                SELECT activity.activity_id, revision.activity_revision_id,
                       revision.revision_no, revision.status, revision.goal,
                       revision.progress_summary, revision.next_safe_step
                FROM armi.activities AS activity
                JOIN armi.activity_revisions AS revision
                  ON revision.activity_revision_id = activity.current_revision_id
                WHERE activity.subject_id = %s AND activity.activity_id = %s
                  AND revision.status = 'in_progress'
                """,
                (fence.subject_id, activity_id.value),
            )
        ).fetchone()
        if row is None:
            return OpportunityAdmissionOutcome(
                OpportunityAdmissionStatus.REJECTED,
                None,
                "LIFE-SCHEDULER-IDLE",
            )
        opportunity_id = uuid7()
        inserted = await (
            await connection.execute(
                """
                INSERT INTO armi.opportunities (
                    opportunity_id, evidence_id, subject_id, scene_id,
                    context_party_id, purpose, eligibility_status,
                    current_disposition, root_opportunity_id,
                    reconsideration_no, source_kind, source_ref,
                    source_version, activity_id) VALUES (
                    %s, NULL, %s, NULL, NULL,
                    'consider_activity_internal_work', 'eligible', 'open',
                    %s, 0, 'activity_revision', %s, %s, %s)
                ON CONFLICT (
                    subject_id, source_kind, source_ref, source_version,
                    purpose, reconsideration_no
                ) DO NOTHING RETURNING opportunity_id
                """,
                (
                    opportunity_id,
                    fence.subject_id,
                    opportunity_id,
                    row[1],
                    int(row[2]),
                    row[0],
                ),
            )
        ).fetchone()
        if inserted is None:
            existing = await (
                await connection.execute(
                    """
                    SELECT opportunity_id
                    FROM armi.opportunities
                    WHERE subject_id = %s AND source_kind = 'activity_revision'
                      AND source_ref = %s AND source_version = %s
                      AND purpose = 'consider_activity_internal_work'
                      AND reconsideration_no = 0
                    """,
                    (fence.subject_id, row[1], int(row[2])),
                )
            ).fetchone()
            if existing is None:
                raise LifeViolation("LIFE-SOURCE-STALE")
            return OpportunityAdmissionOutcome(
                OpportunityAdmissionStatus.DUPLICATE, existing[0]
            )
        await unit_of_work.audit.append(
            AuditDraft(
                AuditEventId(uuid7()),
                AuditReference("runtime", unit_of_work.environment_id),
                Purpose("life.activity.internal_work"),
                "life.activity.internal_work.admitted",
                AuditReference("opportunity", opportunity_id),
                AuditResultStatus.APPLIED,
                TraceId(opportunity_id.hex),
                AuditSensitivity.PRIVATE,
                subject_id=SubjectId(fence.subject_id),
                request=AuditReference("activity_revision", row[1]),
            )
        )
        return OpportunityAdmissionOutcome(
            OpportunityAdmissionStatus.ADMITTED, opportunity_id
        )

    async def admit_creator_outreach(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        *,
        policy: CreatorOutreachPolicy,
    ) -> OpportunityAdmissionOutcome:
        """Admit one objective condition for a subjective outreach decision."""

        fence = unit_of_work.runtime_fence
        if fence is None:
            raise LifeViolation("LIFE-FENCE-REQUIRED")
        if type(policy) is not CreatorOutreachPolicy:
            raise LifeViolation("LIFE-OUTREACH-POLICY")
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        scene = await (
            await connection.execute(
                """
                SELECT scene.scene_id, scene.primary_party_id,
                       latest.interaction_id, latest.received_at,
                       generation.life_generation_id, generation.generation_no,
                       generation.created_at, statement_timestamp()
                FROM armi.interaction_scenes AS scene
                JOIN armi.life_generations AS generation
                  ON generation.subject_id = scene.subject_id
                 AND generation.life_generation_id = %s
                 AND generation.status = 'active'
                LEFT JOIN LATERAL (
                    SELECT interaction.interaction_id,
                           interaction.received_at
                    FROM armi.party_input_interactions AS interaction
                    WHERE interaction.subject_id = scene.subject_id
                      AND interaction.scene_id = scene.scene_id
                      AND interaction.source_party_id = scene.primary_party_id
                    ORDER BY interaction.received_at DESC,
                             interaction.interaction_id DESC
                    LIMIT 1
                ) AS latest ON true
                WHERE scene.subject_id = %s
                  AND scene.current_status = 'open'
                ORDER BY
                    EXISTS (
                        SELECT 1
                        FROM armi.permission_grants AS permission
                        JOIN armi.capabilities AS capability
                          ON capability.capability_id = permission.capability_id
                        WHERE permission.subject_id = scene.subject_id
                          AND permission.interaction_scene_id = scene.scene_id
                          AND permission.creator_party_id = scene.primary_party_id
                          AND permission.status = 'active'
                          AND permission.valid_from <= statement_timestamp()
                          AND statement_timestamp() < permission.valid_until
                          AND permission.consumed_uses < permission.max_uses
                          AND capability.capability_kind = 'creator.scene.reply'
                          AND capability.operation_class = 'send'
                          AND capability.availability_status = 'available'
                    ) DESC,
                    latest.received_at DESC NULLS LAST,
                    (scene.scene_key = 'default') DESC,
                    scene.scene_id
                LIMIT 1
                """,
                (fence.life_generation_id, fence.subject_id),
            )
        ).fetchone()
        if scene is None:
            return OpportunityAdmissionOutcome(
                OpportunityAdmissionStatus.REJECTED,
                None,
                "LIFE-OUTREACH-SCENE-UNAVAILABLE",
            )
        scene_id = scene[0]
        creator_party_id = scene[1]
        latest_input_at = scene[3]
        now = scene[7]
        relationship = await self._relationships.current_for_party(
            unit_of_work.transaction,
            subject_id=fence.subject_id,
            generation_id=fence.life_generation_id,
            other_party_id=creator_party_id,
            scope="creator_social",
        )
        if relationship is not None and not self._relationship_policy.allows_snapshot_outreach(
            relationship
        ):
            return OpportunityAdmissionOutcome(
                OpportunityAdmissionStatus.REJECTED,
                None,
                "LIFE-OUTREACH-RELATIONSHIP-BOUNDARY",
            )
        gate = await (
            await connection.execute(
                """
                SELECT
                    EXISTS (
                        SELECT 1
                        FROM armi.opportunities AS opportunity
                        JOIN armi.action_intents AS intent
                          ON intent.root_opportunity_id = opportunity.opportunity_id
                        JOIN armi.action_operations AS operation
                          ON operation.root_opportunity_id = opportunity.opportunity_id
                        WHERE opportunity.subject_id = %s
                          AND opportunity.scene_id = %s
                          AND opportunity.context_party_id = %s
                          AND opportunity.purpose = 'consider_creator_outreach'
                          AND (
                              operation.phase <> 'terminal'
                              OR operation.outcome = 'unknown'
                          )
                          AND NOT EXISTS (
                              SELECT 1
                              FROM armi.party_input_interactions AS reply
                              WHERE reply.scene_id = intent.scene_id
                                AND reply.source_party_id = intent.context_party_id
                                AND reply.received_at > intent.created_at
                          )
                    ),
                    (
                        SELECT max(episode.created_at)
                        FROM armi.cognitive_episodes AS episode
                        WHERE episode.subject_id = %s
                          AND episode.purpose = 'consider_creator_outreach'
                    ),
                    (
                        SELECT max(item.occurred_at)
                        FROM armi.scene_timeline_items AS item
                        WHERE item.scene_id = %s
                          AND item.source_kind IN (
                              'creator_input', 'party_response'
                          )
                    )
                """,
                (
                    fence.subject_id,
                    scene_id,
                    creator_party_id,
                    fence.subject_id,
                    scene_id,
                ),
            )
        ).fetchone()
        if gate is None:
            raise LifeViolation("LIFE-OUTREACH-GATE")
        if bool(gate[0]):
            return OpportunityAdmissionOutcome(
                OpportunityAdmissionStatus.REJECTED,
                None,
                "LIFE-OUTREACH-AWAITING-CREATOR",
            )
        if gate[1] is not None and now < gate[1] + timedelta(
            seconds=policy.minimum_interval_seconds
        ):
            return OpportunityAdmissionOutcome(
                OpportunityAdmissionStatus.REJECTED,
                None,
                "LIFE-OUTREACH-COOLDOWN",
            )
        if gate[2] is not None and now < gate[2] + timedelta(
            seconds=policy.minimum_interval_seconds
        ):
            return OpportunityAdmissionOutcome(
                OpportunityAdmissionStatus.REJECTED,
                None,
                "LIFE-OUTREACH-COOLDOWN",
            )
        source = None
        if (
            relationship is not None
            and relationship.revision.status.value == "active"
            and relationship.revision.occurred_at > (latest_input_at or scene[6])
            and any(
                item.party_role.value == "subject" and item.status.value == "active"
                for item in relationship.revision.commitments
            )
        ):
            existing = await (
                await connection.execute(
                    """
                    SELECT 1 FROM armi.opportunities
                    WHERE subject_id = %s
                      AND source_kind = 'creator_outreach_relationship'
                      AND source_ref = %s AND source_version = %s
                      AND purpose = 'consider_creator_outreach'
                    """,
                    (
                        fence.subject_id,
                        relationship.current_revision_id,
                        relationship.head_version,
                    ),
                )
            ).fetchone()
            if existing is None:
                source = (
                    "creator_outreach_relationship",
                    relationship.current_revision_id,
                    relationship.head_version,
                    None,
                    relationship.revision.occurred_at,
                )
        if source is None:
            source = await (
                await connection.execute(
                    """
                    SELECT 'creator_outreach_activity',
                           revision.activity_revision_id,
                           activity.head_version, activity.activity_id,
                           revision.created_at
                    FROM armi.activities AS activity
                    JOIN armi.activity_revisions AS revision
                      ON revision.activity_revision_id =
                         activity.current_revision_id
                    WHERE activity.subject_id = %s
                      AND revision.status = 'completed'
                      AND revision.created_at > %s
                      AND NOT EXISTS (
                          SELECT 1 FROM armi.opportunities AS existing
                          WHERE existing.subject_id = activity.subject_id
                            AND existing.source_kind =
                                'creator_outreach_activity'
                            AND existing.source_ref =
                                revision.activity_revision_id
                            AND existing.source_version = activity.head_version
                            AND existing.purpose = 'consider_creator_outreach'
                      )
                    ORDER BY revision.created_at DESC,
                             revision.activity_revision_id DESC
                    LIMIT 1
                    """,
                    (fence.subject_id, latest_input_at or scene[6]),
                )
            ).fetchone()
        if source is None:
            anchor_at = latest_input_at or scene[6]
            available_after = anchor_at + timedelta(
                seconds=policy.absence_after_seconds
            )
            if now < available_after:
                return OpportunityAdmissionOutcome(
                    OpportunityAdmissionStatus.REJECTED,
                    None,
                    "LIFE-OUTREACH-IDLE",
                )
            source = (
                LifeOpportunitySourceKind.CREATOR_OUTREACH_ABSENCE.value,
                scene[2] or scene[4],
                1 if scene[2] is not None else int(scene[5]),
                None,
                available_after,
            )
        opportunity_id = uuid7()
        inserted = await (
            await connection.execute(
                """
                INSERT INTO armi.opportunities (
                    opportunity_id, evidence_id, subject_id, scene_id,
                    context_party_id, purpose, eligibility_status,
                    current_disposition, root_opportunity_id,
                    reconsideration_no, available_after, source_kind,
                    source_ref, source_version, activity_id) VALUES (
                    %s, NULL, %s, %s, %s, 'consider_creator_outreach',
                    'eligible', 'open', %s, 0, %s, %s, %s, %s, %s)
                ON CONFLICT (
                    subject_id, source_kind, source_ref, source_version,
                    purpose, reconsideration_no
                ) DO NOTHING RETURNING opportunity_id
                """,
                (
                    opportunity_id,
                    fence.subject_id,
                    scene_id,
                    creator_party_id,
                    opportunity_id,
                    source[4],
                    str(source[0]),
                    source[1],
                    int(source[2]),
                    source[3],
                ),
            )
        ).fetchone()
        if inserted is None:
            existing = await (
                await connection.execute(
                    """
                    SELECT opportunity_id
                    FROM armi.opportunities
                    WHERE subject_id = %s AND source_kind = %s
                      AND source_ref = %s AND source_version = %s
                      AND purpose = 'consider_creator_outreach'
                      AND reconsideration_no = 0
                    """,
                    (fence.subject_id, str(source[0]), source[1], int(source[2])),
                )
            ).fetchone()
            if existing is None:
                raise LifeViolation("LIFE-SOURCE-STALE")
            return OpportunityAdmissionOutcome(
                OpportunityAdmissionStatus.DUPLICATE, existing[0]
            )
        await unit_of_work.audit.append(
            AuditDraft(
                AuditEventId(uuid7()),
                AuditReference("runtime", unit_of_work.environment_id),
                Purpose("life.creator_outreach"),
                "life.creator_outreach.admitted",
                AuditReference("opportunity", opportunity_id),
                AuditResultStatus.APPLIED,
                TraceId(opportunity_id.hex),
                AuditSensitivity.PRIVATE,
                subject_id=SubjectId(fence.subject_id),
                request=AuditReference(str(source[0]), source[1]),
            )
        )
        return OpportunityAdmissionOutcome(
            OpportunityAdmissionStatus.ADMITTED, opportunity_id
        )


__all__ = ("PostgreSQLLifeOpportunityRepository",)
