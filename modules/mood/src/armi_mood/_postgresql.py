"""PostgreSQL implementation of mood reads and writes."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from statistics import median
from typing import Any, cast
from uuid import UUID, uuid7

import rfc8785
from armi_runtime_foundation import PostgreSQLTransaction

from ._application import MoodApplication
from ._domain import (
    StoredAffectiveEvent,
    StoredEmotionComponent,
    appraisal_to_wire,
    clamp_home_base,
    component_to_wire,
    derive_appraisal,
    derive_effective_snapshot,
    derive_effective_state,
    derive_semantic_appraisal,
    initial_state,
    parse_appraisal_any,
    parse_component,
    parse_state_bytes,
    semantic_appraisal_to_wire,
    semantic_features_to_wire,
    state_to_bytes,
)
from .api import (
    VAD,
    AppraisalEvent,
    AppraisalEventPhase,
    AppraisalTransition,
    CandidateMoodDraft,
    MoodCandidateKind,
    MoodHead,
    MoodSnapshot,
    MoodState,
    MoodViolation,
    SemanticAppraisalEvent,
)

_INITIAL = state_to_bytes(initial_state())


class PostgreSQLMoodOwner:
    __slots__ = ("_application",)

    def __init__(self, application: MoodApplication) -> None:
        self._application = application

    async def open(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def current(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> MoodHead:
        row = await (
            await transaction.execute(
                """SELECT head.current_revision_id, head.mood_version,
                          revision.semantic_payload
                   FROM armi.mood_heads AS head
                   JOIN armi.mood_revisions AS revision
                     ON revision.mood_revision_id=head.current_revision_id
                   WHERE head.subject_id=%s""",
                (subject_id,),
            )
        ).fetchone()
        if row is None:
            raise MoodViolation("MOOD-MISSING")
        canonical = rfc8785.dumps(row[2])
        parse_state_bytes(canonical)
        return MoodHead(row[0], int(row[1]), canonical)

    async def snapshot(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> MoodSnapshot:
        head = await self.current(transaction, subject_id=subject_id)
        state = parse_state_bytes(head.canonical_state)
        clock = await (
            await transaction.execute("SELECT statement_timestamp()")
        ).fetchone()
        if clock is None:
            raise MoodViolation("MOOD-CLOCK")
        as_of = clock[0]
        events = await self._load_events(
            transaction, subject_id=subject_id, as_of=as_of
        )
        current, active, episodes, tendencies = derive_effective_snapshot(
            state.home_base, events, as_of=as_of
        )
        return MoodSnapshot(
            head.current_revision_id,
            head.version,
            as_of,
            state.home_base,
            current,
            active,
            episodes,
            tendencies,
        )

    async def _load_events(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        as_of: datetime,
        days: int = 7,
    ) -> tuple[StoredAffectiveEvent, ...]:
        legacy_rows = await (
            await transaction.execute(
                """SELECT occurred_at, components
                   FROM armi.mood_affective_events
                   WHERE subject_id=%s AND occurred_at <= %s
                     AND occurred_at >= %s - (%s * interval '1 day')
                   ORDER BY occurred_at, mood_affective_event_id""",
                (subject_id, as_of, as_of, days),
            )
        ).fetchall()
        appraisal_rows = await (
            await transaction.execute(
                """SELECT mood_episode_id,transition,event_phase,gist,
                          derived_components,occurred_at
                   FROM armi.mood_appraisal_events
                   WHERE subject_id=%s AND occurred_at <= %s
                     AND occurred_at >= %s - (%s * interval '1 day')
                   ORDER BY occurred_at,mood_appraisal_event_id""",
                (subject_id, as_of, as_of, days),
            )
        ).fetchall()
        events: list[StoredAffectiveEvent] = []
        try:
            for occurred_at, raw_components in legacy_rows:
                events.append(
                    StoredAffectiveEvent(
                        occurred_at, self._stored_components(raw_components)
                    )
                )
            for (
                episode_id,
                transition,
                phase,
                gist,
                raw_components,
                occurred_at,
            ) in appraisal_rows:
                events.append(
                    StoredAffectiveEvent(
                        occurred_at,
                        self._stored_components(raw_components),
                        episode_id,
                        AppraisalTransition(transition),
                        AppraisalEventPhase(phase),
                        str(gist),
                    )
                )
        except MoodViolation, TypeError, ValueError:
            raise MoodViolation("MOOD-EVENT-STORAGE") from None
        events.sort(key=lambda item: item.occurred_at)
        return tuple(events)

    @staticmethod
    def _stored_components(
        raw_components: object,
    ) -> tuple[StoredEmotionComponent, ...]:
        components: list[StoredEmotionComponent] = []
        for raw in cast(list[object], raw_components):
            item = cast(dict[str, object], raw)
            half_life = item.get("half_life_seconds")
            if type(half_life) is not int:
                raise ValueError
            semantic = {
                key: value for key, value in item.items() if key != "half_life_seconds"
            }
            components.append(
                StoredEmotionComponent(parse_component(semantic), half_life)
            )
        return tuple(components)

    async def current_head_count(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> int:
        row = await (
            await transaction.execute(
                "SELECT count(*) FROM armi.mood_heads WHERE subject_id=%s",
                (subject_id,),
            )
        ).fetchone()
        return 0 if row is None else int(row[0])

    async def heads_match(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        drafts: tuple[CandidateMoodDraft, ...],
    ) -> bool:
        if len(drafts) > 1:
            raise MoodViolation("MOOD-DRAFT-COUNT")
        if not drafts:
            return True
        row = await (
            await transaction.execute(
                "SELECT mood_version FROM armi.mood_heads WHERE subject_id=%s FOR UPDATE",
                (subject_id,),
            )
        ).fetchone()
        return row is not None and int(row[0]) == drafts[0].expected_version

    async def commit(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        commit_id: UUID,
        drafts: tuple[CandidateMoodDraft, ...],
    ) -> bool:
        if not drafts:
            return False
        if len(drafts) != 1:
            raise MoodViolation("MOOD-DRAFT-COUNT")
        draft = drafts[0]
        head = await (
            await transaction.execute(
                """SELECT head.current_revision_id,head.mood_version,
                          revision.semantic_payload
                   FROM armi.mood_heads AS head
                   JOIN armi.mood_revisions AS revision
                     ON revision.mood_revision_id=head.current_revision_id
                   WHERE head.subject_id=%s""",
                (subject_id,),
            )
        ).fetchone()
        if head is None or int(head[1]) != draft.expected_version:
            raise MoodViolation("MOOD-HEAD-STALE")
        state = parse_state_bytes(rfc8785.dumps(head[2]))
        next_state = state
        if (
            draft.kind is MoodCandidateKind.APPRAISAL
            and type(draft.appraisal) is SemanticAppraisalEvent
            and not await self._semantic_appraisal_has_change(
                transaction,
                subject_id=subject_id,
                event=draft.appraisal,
            )
        ):
            return False
        if draft.kind is MoodCandidateKind.HOME_BASE_REFLECTION:
            target = await self._reflection_target(
                transaction, subject_id=subject_id, home_base=state.home_base
            )
            home_base = clamp_home_base(state.home_base, target)
            if home_base == state.home_base:
                return False
            next_state = MoodState(
                state.dynamics_version, state.derivation_version, home_base
            )

        revision_id = uuid7()
        version = draft.expected_version + 1
        await transaction.execute(
            """INSERT INTO armi.mood_revisions
               (mood_revision_id,subject_id,mood_version,previous_revision_id,
                origin_kind,origin_ref,subject_commit_id,proposal_ref,
                semantic_payload,privacy_scope)
               VALUES (%s,%s,%s,%s,'subject_commit',%s,%s,%s,%s::jsonb,'private')""",
            (
                revision_id,
                subject_id,
                version,
                head[0],
                commit_id,
                commit_id,
                draft.proposal_ref,
                state_to_bytes(next_state).decode("utf-8"),
            ),
        )
        if draft.kind is MoodCandidateKind.APPRAISAL:
            await self._insert_appraisal(
                transaction,
                subject_id=subject_id,
                revision_id=revision_id,
                draft=draft,
            )
        updated = await (
            await transaction.execute(
                """UPDATE armi.mood_heads
                   SET current_revision_id=%s,mood_version=%s
                   WHERE subject_id=%s AND current_revision_id=%s AND mood_version=%s
                   RETURNING subject_id""",
                (revision_id, version, subject_id, head[0], draft.expected_version),
            )
        ).fetchone()
        if updated is None:
            raise MoodViolation("MOOD-HEAD-STALE")
        return True

    async def _semantic_appraisal_has_change(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        event: SemanticAppraisalEvent,
    ) -> bool:
        previous: AppraisalEvent | SemanticAppraisalEvent | None = None
        if event.transition is not AppraisalTransition.NEW:
            row = await (
                await transaction.execute(
                    """SELECT appraisal_payload,transition
                       FROM armi.mood_appraisal_events
                       WHERE subject_id=%s AND mood_episode_id=%s
                       ORDER BY occurred_at DESC,mood_appraisal_event_id DESC
                       LIMIT 1 FOR UPDATE""",
                    (subject_id, event.previous_episode_id),
                )
            ).fetchone()
            if row is None or row[1] == AppraisalTransition.RESOLVE.value:
                raise MoodViolation("MOOD-APPRAISAL-PREDECESSOR")
            previous = parse_appraisal_any(cast(object, row[0]))
        derived = derive_semantic_appraisal(event, previous=previous)
        return bool(derived.components) or event.transition in {
            AppraisalTransition.REAPPRAISE,
            AppraisalTransition.RESOLVE,
        }

    async def _insert_appraisal(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        revision_id: UUID,
        draft: CandidateMoodDraft,
    ) -> None:
        event = draft.appraisal
        if event is None:
            raise MoodViolation("MOOD-CANDIDATE")
        predecessor_id: UUID | None = None
        previous: AppraisalEvent | SemanticAppraisalEvent | None = None
        if event.transition is AppraisalTransition.NEW:
            episode_id = uuid7()
        else:
            if event.previous_episode_id is None:
                raise MoodViolation("MOOD-APPRAISAL-PREDECESSOR")
            row = await (
                await transaction.execute(
                    """SELECT mood_appraisal_event_id,appraisal_payload,transition
                       FROM armi.mood_appraisal_events
                       WHERE subject_id=%s AND mood_episode_id=%s
                       ORDER BY occurred_at DESC,mood_appraisal_event_id DESC
                       LIMIT 1 FOR UPDATE""",
                    (subject_id, event.previous_episode_id),
                )
            ).fetchone()
            if row is None or row[2] == AppraisalTransition.RESOLVE.value:
                raise MoodViolation("MOOD-APPRAISAL-PREDECESSOR")
            predecessor_id = row[0]
            previous = parse_appraisal_any(cast(object, row[1]))
            episode_id = event.previous_episode_id
        if isinstance(event, SemanticAppraisalEvent):
            derived = derive_semantic_appraisal(event, previous=previous)
            raw_appraisal = semantic_appraisal_to_wire(event)
            appraisal_mapping_version = "semantic-anchors.v1"
            derived_appraisal = semantic_features_to_wire(event.appraisal)
            derivation_version = "cpm-fuzzy.v2"
        else:
            derived = derive_appraisal(
                event,
                previous=previous if isinstance(previous, AppraisalEvent) else None,
            )
            raw_appraisal = appraisal_to_wire(event)
            appraisal_mapping_version = "direct-scale.v1"
            derived_appraisal = {
                "schema_version": "armi.mood-derived-appraisal.v1",
                "vector": raw_appraisal["appraisal"],
            }
            derivation_version = "cpm-fuzzy.v1"
        if not derived.components and event.transition in {
            AppraisalTransition.NEW,
            AppraisalTransition.REINFORCE,
        }:
            raise MoodViolation("MOOD-APPRAISAL-NO-AFFECT")
        components = [
            component_to_wire(item.component, half_life_seconds=item.half_life_seconds)
            for item in derived.components
        ]
        await transaction.execute(
            """INSERT INTO armi.mood_appraisal_events
               (mood_appraisal_event_id,subject_id,mood_revision_id,mood_episode_id,
                previous_appraisal_event_id,transition,event_phase,gist,
                basis_ordinals,appraisal_payload,appraisal_mapping_version,
                derived_appraisal_payload,importance,derived_vad,derived_components,
                derivation_version,dynamics_version,privacy_scope)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s::jsonb,%s,
                       %s::jsonb,%s::jsonb,%s,'recency-reappraisal.v1','private')""",
            (
                uuid7(),
                subject_id,
                revision_id,
                episode_id,
                predecessor_id,
                event.transition.value,
                event.phase.value,
                event.gist,
                list(draft.basis_ordinals),
                rfc8785.dumps(cast(Any, raw_appraisal)).decode("utf-8"),
                appraisal_mapping_version,
                rfc8785.dumps(cast(Any, derived_appraisal)).decode("utf-8"),
                derived.importance,
                rfc8785.dumps(
                    {
                        "valence": derived.target.valence,
                        "arousal": derived.target.arousal,
                        "dominance": derived.target.dominance,
                    }
                ).decode("utf-8"),
                rfc8785.dumps(cast(Any, components)).decode("utf-8"),
                derivation_version,
            ),
        )

    async def _reflection_target(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        home_base: VAD,
    ) -> VAD:
        last_change = await (
            await transaction.execute(
                """SELECT current.created_at
                   FROM armi.mood_revisions AS current
                   LEFT JOIN armi.mood_revisions AS previous
                     ON previous.mood_revision_id=current.previous_revision_id
                   WHERE current.subject_id=%s
                     AND (previous.mood_revision_id IS NULL OR
                          current.semantic_payload->'home_base'
                            IS DISTINCT FROM previous.semantic_payload->'home_base')
                   ORDER BY current.mood_version DESC LIMIT 1""",
                (subject_id,),
            )
        ).fetchone()
        if last_change is None:
            return home_base
        row = await (
            await transaction.execute(
                """SELECT count(*),min(occurred_at),max(occurred_at)
                   FROM armi.mood_appraisal_events
                   WHERE subject_id=%s AND occurred_at >= %s
                     AND occurred_at >= statement_timestamp() - interval '30 days'""",
                (subject_id, last_change[0]),
            )
        ).fetchone()
        if (
            row is None
            or int(row[0]) < 12
            or row[1] is None
            or row[2] is None
            or row[2] - row[1] < timedelta(days=7)
        ):
            return home_base
        clock = await (
            await transaction.execute("SELECT statement_timestamp()")
        ).fetchone()
        if clock is None:
            raise MoodViolation("MOOD-CLOCK")
        now = cast(datetime, clock[0]).astimezone(UTC)
        lower = max(
            cast(datetime, last_change[0]).astimezone(UTC), now - timedelta(days=30)
        )
        first_day = datetime.combine(lower.date() + timedelta(days=1), time(), UTC)
        final_day = datetime.combine(now.date(), time(), UTC)
        days: list[datetime] = []
        cursor = first_day
        while cursor + timedelta(days=1) <= final_day:
            days.append(cursor)
            cursor += timedelta(days=1)
        if len(days) < 7:
            return home_base
        daily: list[VAD] = []
        for day in days:
            samples: list[VAD] = []
            for hour in (0, 6, 12, 18):
                as_of = day + timedelta(hours=hour)
                events = await self._load_events(
                    transaction, subject_id=subject_id, as_of=as_of
                )
                current, _active = derive_effective_state(
                    home_base, events, as_of=as_of
                )
                samples.append(current)
            daily.append(
                VAD(
                    round(sum(item.valence for item in samples) / len(samples)),
                    round(sum(item.arousal for item in samples) / len(samples)),
                    round(sum(item.dominance for item in samples) / len(samples)),
                )
            )
        return VAD(
            round(median(item.valence for item in daily)),
            round(median(item.arousal for item in daily)),
            round(median(item.dominance for item in daily)),
        )

    async def initialize(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> None:
        revision_id = uuid7()
        await transaction.execute(
            """INSERT INTO armi.mood_revisions
               (mood_revision_id,subject_id,mood_version,origin_kind,origin_ref,
                semantic_payload,privacy_scope)
               VALUES (%s,%s,1,'bootstrap',%s,%s::jsonb,'private')""",
            (revision_id, subject_id, subject_id, _INITIAL.decode("utf-8")),
        )
        await transaction.execute(
            """INSERT INTO armi.mood_heads
               (subject_id,current_revision_id,mood_version) VALUES (%s,%s,1)""",
            (subject_id, revision_id),
        )


__all__ = ("PostgreSQLMoodOwner",)
