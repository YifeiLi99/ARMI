"""PostgreSQL ownership for autonomous life opportunity admission."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid7

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
from armi_runtime_foundation import (
    PostgreSQLRuntimeUnitOfWork,
    PostgreSQLTransaction,
)
from armi_sleep.api import SleepReadPort
from armi_subject_state.api import SubjectStateReadPort, SubjectStateViolation

from .api import (
    CreatorOutreachPolicy,
    LifeOpportunityFactsPort,
    LifeOpportunitySourceKind,
    LifeViolation,
    OpportunityAdmissionOutcome,
    OpportunityAdmissionStatus,
)


@dataclass(frozen=True, slots=True)
class _AttentionRootState:
    opportunity_id: UUID
    disposition: str
    retry_ready: bool
    successor_id: UUID | None


class PostgreSQLLifeOpportunityRepository:
    """Admit one source-backed root opportunity under the active Runtime fence."""

    __slots__ = (
        "_activities",
        "_facts",
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
        facts: LifeOpportunityFactsPort,
    ) -> None:
        self._activities = activities
        self._materials = materials
        self._relationships = relationships
        self._relationship_policy = relationship_policy
        self._sleep = sleep
        self._subject_state = subject_state
        self._facts = facts

    async def admit_generation_available(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
    ) -> OpportunityAdmissionOutcome:
        fence = unit_of_work.runtime_fence
        if fence is None:
            raise LifeViolation("LIFE-FENCE-REQUIRED")
        connection = unit_of_work.transaction
        generation = await self._facts.generation(unit_of_work)
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
                    generation.generation_no,
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
                    (
                        fence.subject_id,
                        fence.life_generation_id,
                        generation.generation_no,
                    ),
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
                       )
                """,
                (fence.subject_id,),
            )
        ).fetchone()
        if state is None:
            raise LifeViolation("LIFE-SCHEDULER-STATE")
        active_cognition = await self._facts.active_cognition_count(
            connection, subject_id=fence.subject_id
        )
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
                active_cognition,
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
            existing = await self._attention_root_state(
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
                        ON CONFLICT (
                            subject_id, source_kind, source_ref, source_version,
                            purpose, reconsideration_no
                        ) DO NOTHING
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
                       )
                """,
                (fence.subject_id,),
            )
        ).fetchone()
        if state is None:
            raise LifeViolation("LIFE-SCHEDULER-STATE")
        active_cognition = await self._facts.active_cognition_count(
            connection, subject_id=fence.subject_id
        )
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
        if active_cognition >= model_concurrency - 1:
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

    async def _attention_root_state(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        revision_id: UUID,
        revision_no: int,
    ) -> _AttentionRootState | None:
        row = await (
            await transaction.execute(
                """
                SELECT root.opportunity_id, root.current_disposition,
                       root.resolved_at, successor.opportunity_id
                FROM armi.opportunities AS root
                LEFT JOIN armi.opportunities AS successor
                  ON successor.predecessor_opportunity_id = root.opportunity_id
                WHERE root.subject_id = %s
                  AND root.source_kind = 'activity_revision'
                  AND root.source_ref = %s AND root.source_version = %s
                  AND root.purpose = 'consider_activity_attention'
                  AND root.reconsideration_no = 0
                """,
                (subject_id, revision_id, revision_no),
            )
        ).fetchone()
        if row is None:
            return None
        facts = await self._facts.attention_retry(
            transaction,
            subject_id=subject_id,
            root_opportunity_id=row[0],
            resolved_at=row[2],
        )
        return _AttentionRootState(
            row[0],
            str(row[1]),
            facts.failed_ready
            or (
                facts.need_information_at is not None and facts.creator_input_after_need
            ),
            row[3],
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
        outreach = await self._facts.outreach(unit_of_work)
        if outreach is None:
            return OpportunityAdmissionOutcome(
                OpportunityAdmissionStatus.REJECTED,
                None,
                "LIFE-OUTREACH-SCENE-UNAVAILABLE",
            )
        scene_id = outreach.scene_id
        creator_party_id = outreach.creator_party_id
        latest_input_at = outreach.latest_input_at
        now = outreach.now
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
        if outreach.awaiting_creator:
            return OpportunityAdmissionOutcome(
                OpportunityAdmissionStatus.REJECTED,
                None,
                "LIFE-OUTREACH-AWAITING-CREATOR",
            )
        if outreach.last_cognition_at is not None and now < (
            outreach.last_cognition_at
            + timedelta(seconds=policy.minimum_interval_seconds)
        ):
            return OpportunityAdmissionOutcome(
                OpportunityAdmissionStatus.REJECTED,
                None,
                "LIFE-OUTREACH-COOLDOWN",
            )
        if outreach.last_timeline_at is not None and now < (
            outreach.last_timeline_at
            + timedelta(seconds=policy.minimum_interval_seconds)
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
            and relationship.revision.occurred_at
            > (latest_input_at or outreach.generation_created_at)
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
                after=latest_input_at or outreach.generation_created_at,
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
            anchor_at = latest_input_at or outreach.generation_created_at
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
                outreach.latest_input_id or outreach.generation_id,
                1 if outreach.latest_input_id is not None else outreach.generation_no,
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
