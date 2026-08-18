"""PostgreSQL implementation of mood reads and writes."""

from __future__ import annotations

from datetime import timedelta
from typing import cast
from uuid import UUID, uuid7

import rfc8785
from armi_runtime_foundation import PostgreSQLTransaction

from ._application import MoodApplication
from ._domain import (
    StoredAffectiveEvent,
    StoredEmotionComponent,
    clamp_home_base,
    component_to_wire,
    derive_effective_state,
    half_life_seconds,
    initial_state,
    parse_component,
    parse_state_bytes,
    state_to_bytes,
)
from .api import (
    CandidateMoodDraft,
    MoodCandidateKind,
    MoodHead,
    MoodSnapshot,
    MoodState,
    MoodViolation,
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
        rows = await (
            await transaction.execute(
                """SELECT occurred_at, components
                   FROM armi.mood_affective_events
                   WHERE subject_id=%s
                     AND occurred_at >= %s - interval '7 days'
                   ORDER BY occurred_at, mood_affective_event_id""",
                (subject_id, as_of),
            )
        ).fetchall()
        events: list[StoredAffectiveEvent] = []
        try:
            for occurred_at, raw_components in rows:
                components: list[StoredEmotionComponent] = []
                for raw in cast(list[object], raw_components):
                    item = cast(dict[str, object], raw)
                    half_life = item.get("half_life_seconds")
                    if type(half_life) is not int:
                        raise ValueError
                    semantic = {key: value for key, value in item.items() if key != "half_life_seconds"}
                    components.append(
                        StoredEmotionComponent(parse_component(semantic), half_life)
                    )
                events.append(StoredAffectiveEvent(occurred_at, tuple(components)))
        except (MoodViolation, TypeError, ValueError):
            raise MoodViolation("MOOD-EVENT-STORAGE") from None
        current, active = derive_effective_state(
            state.home_base, tuple(events), as_of=as_of
        )
        return MoodSnapshot(
            head.current_revision_id,
            head.version,
            as_of,
            state.home_base,
            current,
            active,
        )

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
        if draft.kind is MoodCandidateKind.HOME_BASE_REFLECTION:
            await self._require_reflection_evidence(transaction, subject_id=subject_id)
            if draft.target_home_base is None:
                raise MoodViolation("MOOD-CANDIDATE")
            home_base = clamp_home_base(state.home_base, draft.target_home_base)
            if home_base == state.home_base:
                raise MoodViolation("MOOD-REFLECTION-NOOP")
            next_state = MoodState(state.dynamics_version, home_base)

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
        if draft.kind is MoodCandidateKind.EVENT:
            await self._insert_event(
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

    async def _insert_event(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        revision_id: UUID,
        draft: CandidateMoodDraft,
    ) -> None:
        event = draft.event
        if event is None:
            raise MoodViolation("MOOD-CANDIDATE")
        components = [
            component_to_wire(
                item,
                half_life_seconds=half_life_seconds(
                    importance=event.importance, intensity=item.intensity
                ),
            )
            for item in event.components
        ]
        await transaction.execute(
            """INSERT INTO armi.mood_affective_events
               (mood_affective_event_id,subject_id,mood_revision_id,
                importance,components,privacy_scope)
               VALUES (%s,%s,%s,%s,%s::jsonb,'private')""",
            (
                uuid7(),
                subject_id,
                revision_id,
                event.importance,
                rfc8785.dumps(components).decode("utf-8"),
            ),
        )

    async def _require_reflection_evidence(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> None:
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
            raise MoodViolation("MOOD-REFLECTION-EVIDENCE")
        row = await (
            await transaction.execute(
                """SELECT count(*),min(occurred_at),max(occurred_at)
                   FROM armi.mood_affective_events
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
            raise MoodViolation("MOOD-REFLECTION-EVIDENCE")

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
