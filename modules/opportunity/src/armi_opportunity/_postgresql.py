"""PostgreSQL ownership for autonomous life opportunity admission."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid7

from armi_activity.api import (
    ActivityId,
    ActivityReadPort,
    ActivityScheduler,
    ActivitySchedulingDisposition,
    ActivitySchedulingSnapshot,
)
from armi_kernel.application import (
    AuditDraft,
    AuditEventId,
    AuditReference,
    AuditResultStatus,
    AuditSensitivity,
)
from armi_kernel.contracts import (
    ContractViolation,
    Purpose,
    SubjectId,
    TraceId,
)
from armi_material.api import MaterialReadPort
from armi_relationship.api import RelationshipPolicyPort, RelationshipReadPort
from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWork
from armi_sleep.api import SleepReadPort
from armi_subject_state.api import SubjectStateReadPort, SubjectStateViolation

from .api import (
    CreatorOutreachPolicy,
    LifeOpportunitySourceKind,
    LifeViolation,
    OpportunityAdmissionOutcome,
    OpportunityAdmissionStatus,
)


class PostgreSQLLifeOpportunityRepository:
    """Admit one source-backed root opportunity under the active Runtime fence."""

    __slots__ = (
        "_activities",
        "_materials",
        "_relationship_policy",
        "_relationships",
        "_sleep",
        "_subject_state",
    )

    def __init__(
        self,
        relationships: RelationshipReadPort,
        relationship_policy: RelationshipPolicyPort,
        sleep: SleepReadPort,
        activities: ActivityReadPort,
        materials: MaterialReadPort,
        subject_state: SubjectStateReadPort,
    ) -> None:
        self._activities = activities
        self._materials = materials
        self._relationships = relationships
        self._relationship_policy = relationship_policy
        self._sleep = sleep
        self._subject_state = subject_state

    async def admit_generation_available(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
    ) -> OpportunityAdmissionOutcome:
        fence = unit_of_work.runtime_fence
        if fence is None:
            raise LifeViolation("LIFE-FENCE-REQUIRED")
        connection = unit_of_work.transaction
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
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
    ) -> OpportunityAdmissionOutcome:
        """Offer one current active ARMI-owned material for autonomous consideration."""

        fence = unit_of_work.runtime_fence
        if fence is None:
            raise LifeViolation("LIFE-FENCE-REQUIRED")
        connection = unit_of_work.transaction
        source = await self._materials.next_opportunity_source(
            unit_of_work.transaction,
            subject_id=fence.subject_id,
            generation_id=fence.life_generation_id,
        )
        if source is None:
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
                    source.revision_id,
                    source.head_version,
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
                    (fence.subject_id, source.revision_id, source.head_version),
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
                request=AuditReference("life_material_revision", source.revision_id),
            )
        )
        return OpportunityAdmissionOutcome(
            OpportunityAdmissionStatus.ADMITTED,
            opportunity_id,
        )

    async def admit_activity_attention(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        model_concurrency: int,
    ) -> OpportunityAdmissionOutcome:
        fence = unit_of_work.runtime_fence
        if fence is None:
            raise LifeViolation("LIFE-FENCE-REQUIRED")
        connection = unit_of_work.transaction
        maintenance = await self._sleep.active_maintenance(
            connection, subject_id=fence.subject_id
        )
        state = await (
            await connection.execute(
                """
                SELECT EXISTS (
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
                """,
                (fence.subject_id,),
            )
        ).fetchone()
        if state is None:
            raise LifeViolation("LIFE-SCHEDULER-STATE")
        if maintenance is not None:
            return OpportunityAdmissionOutcome(
                OpportunityAdmissionStatus.REJECTED,
                None,
                "LIFE-BACKPRESSURE-MAINTENANCE",
            )
        try:
            life_mode = await self._subject_state.life_mode(
                unit_of_work.transaction, subject_id=fence.subject_id
            )
            active_ids = tuple(
                ActivityId(value) for value in life_mode.active_activity_ids
            )
        except ContractViolation, SubjectStateViolation:
            raise LifeViolation("LIFE-SCHEDULER-FOCUS") from None
        heads = await self._activities.scheduling_heads(
            unit_of_work.transaction, subject_id=fence.subject_id
        )
        decision = ActivityScheduler().select(
            ActivitySchedulingSnapshot(
                datetime.now(UTC),
                heads,
                active_ids,
                bool(state[0]),
                model_concurrency,
                int(state[1]),
            )
        )
        if decision.disposition is not ActivitySchedulingDisposition.ADMIT:
            return OpportunityAdmissionOutcome(
                OpportunityAdmissionStatus.REJECTED,
                None,
                decision.reason_code or "LIFE-SCHEDULER-IDLE",
            )
        selected = next(
            item for item in heads if item.revision_id == decision.activity_revision_id
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
                    selected.revision_id,
                    selected.revision_no,
                    selected.activity_id.value,
                ),
            )
        ).fetchone()
        if inserted is None:
            existing = await self._activities.attention_root_state(
                unit_of_work.transaction,
                subject_id=fence.subject_id,
                revision_id=selected.revision_id,
                revision_no=selected.revision_no,
            )
            if existing is None:
                raise LifeViolation("LIFE-SOURCE-STALE")
            if existing.successor_id is not None:
                return OpportunityAdmissionOutcome(
                    OpportunityAdmissionStatus.DUPLICATE, existing.successor_id
                )
            if existing.disposition == "resolved" and existing.retry_ready:
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
                            existing.opportunity_id,
                            existing.opportunity_id,
                            selected.revision_id,
                            selected.revision_no,
                            selected.activity_id.value,
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
                            request=AuditReference(
                                "activity_revision", selected.revision_id
                            ),
                        )
                    )
                    return OpportunityAdmissionOutcome(
                        OpportunityAdmissionStatus.ADMITTED, retry_id
                    )
            return OpportunityAdmissionOutcome(
                OpportunityAdmissionStatus.DUPLICATE, existing.opportunity_id
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
                request=AuditReference("activity_revision", selected.revision_id),
            )
        )
        return OpportunityAdmissionOutcome(
            OpportunityAdmissionStatus.ADMITTED, opportunity_id
        )

    async def admit_activity_internal_work(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
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
        connection = unit_of_work.transaction
        maintenance = await self._sleep.active_maintenance(
            connection, subject_id=fence.subject_id
        )
        state = await (
            await connection.execute(
                """
                SELECT EXISTS (
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
                """,
                (fence.subject_id,),
            )
        ).fetchone()
        if state is None:
            raise LifeViolation("LIFE-SCHEDULER-STATE")
        if maintenance is not None:
            return OpportunityAdmissionOutcome(
                OpportunityAdmissionStatus.REJECTED,
                None,
                "LIFE-BACKPRESSURE-MAINTENANCE",
            )
        if bool(state[0]):
            return OpportunityAdmissionOutcome(
                OpportunityAdmissionStatus.REJECTED,
                None,
                "LIFE-BACKPRESSURE-INTERNAL-WORK-OUTSTANDING",
            )
        if int(state[1]) >= model_concurrency - 1:
            return OpportunityAdmissionOutcome(
                OpportunityAdmissionStatus.REJECTED,
                None,
                "LIFE-BACKPRESSURE-COGNITION-CAPACITY",
            )
        try:
            life_mode = await self._subject_state.life_mode(
                unit_of_work.transaction, subject_id=fence.subject_id
            )
        except SubjectStateViolation:
            raise LifeViolation("LIFE-SCHEDULER-FOCUS") from None
        if len(life_mode.active_activity_ids) != 1:
            return OpportunityAdmissionOutcome(
                OpportunityAdmissionStatus.REJECTED,
                None,
                "LIFE-SCHEDULER-IDLE",
            )
        try:
            activity_id = ActivityId(life_mode.active_activity_ids[0])
        except ContractViolation:
            raise LifeViolation("LIFE-SCHEDULER-FOCUS") from None
        row = await self._activities.focused_work_head(
            unit_of_work.transaction,
            subject_id=fence.subject_id,
            activity_id=activity_id.value,
        )
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
                    row.revision_id,
                    row.revision_no,
                    row.activity_id,
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
                    (fence.subject_id, row.revision_id, row.revision_no),
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
                request=AuditReference("activity_revision", row.revision_id),
            )
        )
        return OpportunityAdmissionOutcome(
            OpportunityAdmissionStatus.ADMITTED, opportunity_id
        )

    async def admit_creator_outreach(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        policy: CreatorOutreachPolicy,
    ) -> OpportunityAdmissionOutcome:
        """Admit one objective condition for a subjective outreach decision."""

        fence = unit_of_work.runtime_fence
        if fence is None:
            raise LifeViolation("LIFE-FENCE-REQUIRED")
        if type(policy) is not CreatorOutreachPolicy:
            raise LifeViolation("LIFE-OUTREACH-POLICY")
        connection = unit_of_work.transaction
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
        if (
            relationship is not None
            and not self._relationship_policy.allows_snapshot_outreach(relationship)
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
                        LEFT JOIN armi.action_intent_revisions AS revision
                          ON revision.action_intent_revision_id =
                             intent.current_revision_id
                        LEFT JOIN armi.policy_decisions AS policy
                          ON policy.action_intent_revision_id =
                             revision.action_intent_revision_id
                         AND policy.is_current
                        LEFT JOIN armi.effects AS effect
                          ON effect.action_intent_id = intent.action_intent_id
                        WHERE opportunity.subject_id = %s
                          AND opportunity.scene_id = %s
                          AND opportunity.context_party_id = %s
                          AND opportunity.purpose = 'consider_creator_outreach'
                          AND (
                              policy.policy_decision_id IS NULL
                              OR (
                                  policy.decision_outcome = 'allowed'
                                  AND (
                                      effect.effect_id IS NULL
                                      OR effect.status IN (
                                          'registered', 'dispatching', 'unknown'
                                      )
                                  )
                              )
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
            activity_source = await self._activities.completed_outreach_source(
                unit_of_work.transaction,
                subject_id=fence.subject_id,
                after=latest_input_at or scene[6],
            )
            if activity_source is not None:
                source = (
                    "creator_outreach_activity",
                    activity_source.revision_id,
                    activity_source.head_version,
                    activity_source.activity_id,
                    activity_source.occurred_at,
                )
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
