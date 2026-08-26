"""Short-transaction PostgreSQL owner for one live-voice session."""

from __future__ import annotations

from typing import Literal, cast
from uuid import UUID, uuid7

from armi_runtime_foundation import (
    PostgreSQLRuntimeUnitOfWorkFactory,
    PostgreSQLTransaction,
)

from .api import (
    AttemptOutcome,
    FastReplyDecision,
    LiveVoiceBinding,
    LiveVoiceSessionState,
    LiveVoiceViolation,
    PlaybackExtent,
    VoiceProviderBinding,
    VoiceTimelinePort,
    VoiceTurnSnapshot,
)


def _require_voice_error(code: str | None, outcome: AttemptOutcome) -> str | None:
    requires_error = outcome is not AttemptOutcome.COMPLETED
    if requires_error != (code is not None):
        raise LiveVoiceViolation("VOICE-JOURNAL-OUTCOME", "voice outcome is invalid")
    if code is not None and (
        not code.startswith("VOICE-")
        or len(code) > 126
        or not all(
            character.isupper() or character.isdigit() or character == "-"
            for character in code
        )
    ):
        raise LiveVoiceViolation("VOICE-JOURNAL-ERROR", "voice error code is invalid")
    return code


class PostgreSQLLiveVoiceJournal:
    """Own live-voice facts while provider/device I/O stays outside transactions."""

    __slots__ = (
        "_binding",
        "_creator_party_id",
        "_factory",
        "_scene_id",
        "_subject_id",
        "_timeline",
    )

    def __init__(
        self,
        *,
        factory: PostgreSQLRuntimeUnitOfWorkFactory,
        subject_id: UUID,
        creator_party_id: UUID,
        scene_id: UUID,
        binding: LiveVoiceBinding,
        timeline: VoiceTimelinePort,
    ) -> None:
        if any(
            type(value) is not UUID or value.version != 7
            for value in (subject_id, creator_party_id, scene_id)
        ):
            raise LiveVoiceViolation("VOICE-JOURNAL-SCOPE", "voice scope is invalid")
        self._factory = factory
        self._subject_id = subject_id
        self._creator_party_id = creator_party_id
        self._scene_id = scene_id
        self._binding = binding
        self._timeline = timeline

    async def recent_turn(self) -> VoiceTurnSnapshot | None:
        async with self._factory.unit_of_work(read_only=True) as unit:
            row = await (
                await unit.transaction.execute(
                    "SELECT turn_id,result_status,playback_extent,frames_written,error_code "
                    "FROM armi.live_voice_turns ORDER BY created_at DESC LIMIT 1"
                )
            ).fetchone()
        if row is None:
            return None
        return VoiceTurnSnapshot(
            UUID(str(row[0])),
            cast(
                Literal[
                    "recognizing",
                    "thinking",
                    "speaking",
                    "waiting_slow",
                    "completed",
                    "failed",
                    "partial",
                    "unknown",
                    "silent",
                ],
                str(row[1]),
            ),
            PlaybackExtent(str(row[2])),
            int(row[3]),
            None if row[4] is None else str(row[4]),
        )

    async def open_session(self, *, session_id: UUID) -> None:
        async with self._factory.unit_of_work() as unit:
            await unit.transaction.execute(
                """INSERT INTO armi.live_voice_sessions
                   (session_id,subject_id,creator_party_id,scene_id,state,
                    input_host_api,input_device_name,
                    output_host_api,output_device_name)
                   VALUES (%s,%s,%s,%s,'starting',%s,%s,%s,%s)""",
                (
                    session_id,
                    self._subject_id,
                    self._creator_party_id,
                    self._scene_id,
                    self._binding.input_host_api,
                    self._binding.input_device_name,
                    self._binding.output_host_api,
                    self._binding.output_device_name,
                ),
            )

    async def set_session_state(
        self,
        *,
        session_id: UUID,
        state: LiveVoiceSessionState,
        context_version: str | None = None,
    ) -> None:
        if state in {LiveVoiceSessionState.IDLE, LiveVoiceSessionState.UNAVAILABLE}:
            raise LiveVoiceViolation("VOICE-JOURNAL-STATE", "voice state is terminal")
        async with self._factory.unit_of_work() as unit:
            result = await unit.transaction.execute(
                """UPDATE armi.live_voice_sessions
                   SET state=%s,context_version=COALESCE(%s,context_version)
                   WHERE session_id=%s AND ended_at IS NULL""",
                (state.value, context_version, session_id),
            )
            if result.rowcount != 1:
                raise LiveVoiceViolation(
                    "VOICE-JOURNAL-STATE", "voice session is closed"
                )

    async def close_session(
        self, *, session_id: UUID, error_code: str | None = None
    ) -> None:
        if error_code is not None:
            _require_voice_error(error_code, AttemptOutcome.FAILED)
        async with self._factory.unit_of_work() as unit:
            await unit.transaction.execute(
                """UPDATE armi.live_voice_sessions
                   SET state=%s,ended_at=statement_timestamp(),error_code=%s
                   WHERE session_id=%s AND ended_at IS NULL""",
                ("unavailable" if error_code else "stopped", error_code, session_id),
            )

    async def begin_turn(
        self,
        *,
        session_id: UUID,
        turn_id: UUID,
        turn_no: int,
        context_version: str,
    ) -> None:
        async with self._factory.unit_of_work() as unit:
            await unit.transaction.execute(
                """INSERT INTO armi.live_voice_turns
                   (turn_id,session_id,turn_no,model_identity,context_version,
                    result_status)
                   VALUES (%s,%s,%s,%s,%s,'recognizing')""",
                (
                    turn_id,
                    session_id,
                    turn_no,
                    self._binding.llm.model_identity,
                    context_version,
                ),
            )

    async def record_transcript(
        self,
        *,
        turn_id: UUID,
        transcript: str | None,
        interaction_id: UUID | None,
    ) -> None:
        async with self._factory.unit_of_work() as unit:
            result = await unit.transaction.execute(
                """UPDATE armi.live_voice_turns
                   SET final_transcript=%s,interaction_id=%s,
                       speech_ended_at=statement_timestamp(),result_status='thinking'
                   WHERE turn_id=%s AND completed_at IS NULL""",
                (transcript, interaction_id, turn_id),
            )
            if result.rowcount != 1:
                raise LiveVoiceViolation("VOICE-JOURNAL-TURN", "voice turn is closed")

    async def record_decision(
        self, *, turn_id: UUID, decision: FastReplyDecision
    ) -> None:
        async with self._factory.unit_of_work() as unit:
            result = await unit.transaction.execute(
                """UPDATE armi.live_voice_turns
                   SET decision_kind=%s
                   WHERE turn_id=%s AND completed_at IS NULL""",
                (decision.kind.value.lower(), turn_id),
            )
            if result.rowcount != 1:
                raise LiveVoiceViolation("VOICE-JOURNAL-TURN", "voice turn is closed")

    async def settle_turn(
        self,
        *,
        turn_id: UUID,
        outcome: AttemptOutcome,
        error_code: str | None = None,
        silent: bool = False,
    ) -> None:
        error_code = _require_voice_error(error_code, outcome)
        status = "silent" if silent else outcome.value
        async with self._factory.unit_of_work() as unit:
            playback = await (
                await unit.transaction.execute(
                    "SELECT result_status,frames_written FROM "
                    "armi.live_voice_playback_attempts WHERE turn_id=%s "
                    "ORDER BY registered_at DESC LIMIT 1",
                    (turn_id,),
                )
            ).fetchone()
            response = await (
                await unit.transaction.execute(
                    "SELECT COALESCE(string_agg(body,'' ORDER BY fragment_no),'') "
                    "FROM armi.live_voice_text_fragments WHERE turn_id=%s "
                    "AND data_rights_redacted_at IS NULL",
                    (turn_id,),
                )
            ).fetchone()
            if response is None:
                raise LiveVoiceViolation("VOICE-JOURNAL-TURN", "voice turn is absent")
            frames_written = 0 if playback is None else int(playback[1])
            extent = "none"
            if playback is not None:
                playback_status = str(playback[0])
                if playback_status == "completed":
                    extent = "complete"
                    status = "completed"
                    error_code = None
                elif playback_status == "partial":
                    extent = "partial_prefix"
                    status = "partial"
                elif playback_status == "unknown":
                    extent = "unknown_completion"
                    status = "unknown"
            result = await unit.transaction.execute(
                """UPDATE armi.live_voice_turns
                   SET result_status=%s,registered_response_text=%s,
                       playback_extent=%s,frames_written=%s,error_code=%s,
                       completed_at=statement_timestamp()
                   WHERE turn_id=%s AND completed_at IS NULL
                   RETURNING first_audio_at""",
                (status, str(response[0]), extent, frames_written, error_code, turn_id),
            )
            row = await result.fetchone()
            if row is None:
                raise LiveVoiceViolation("VOICE-JOURNAL-TURN", "voice turn is closed")
            if status == "completed" and extent == "complete" and response[0]:
                if row[0] is None:
                    raise LiveVoiceViolation(
                        "VOICE-JOURNAL-PLAYBACK", "voice playback is invalid"
                    )
                await self._timeline.record_live_voice_response(
                    unit.transaction,
                    scene_id=self._scene_id,
                    turn_id=turn_id,
                    occurred_at=row[0],
                )

    async def begin_provider_attempt(
        self, *, turn_id: UUID, binding: VoiceProviderBinding
    ) -> UUID:
        attempt_id = uuid7()
        async with self._factory.unit_of_work() as unit:
            await unit.transaction.execute(
                """INSERT INTO armi.live_voice_provider_attempts
                   (provider_attempt_id,turn_id,service_kind,provider,
                    resource_id,model_identity,dispatch_state,result_status)
                   VALUES (%s,%s,%s,%s,%s,%s,'prepared','started')""",
                (
                    attempt_id,
                    turn_id,
                    binding.service.value,
                    binding.provider,
                    binding.resource_id,
                    binding.model_identity,
                ),
            )
        return attempt_id

    async def mark_provider_dispatched(self, *, attempt_id: UUID) -> None:
        async with self._factory.unit_of_work() as unit:
            result = await unit.transaction.execute(
                """UPDATE armi.live_voice_provider_attempts
                   SET dispatch_state='dispatched',
                       dispatched_at=statement_timestamp()
                   WHERE provider_attempt_id=%s AND dispatch_state='prepared'
                     AND settled_at IS NULL""",
                (attempt_id,),
            )
            if result.rowcount != 1:
                raise LiveVoiceViolation(
                    "VOICE-JOURNAL-ATTEMPT", "voice attempt is closed"
                )

    async def mark_provider_first_result(self, *, attempt_id: UUID) -> None:
        async with self._factory.unit_of_work() as unit:
            await unit.transaction.execute(
                """UPDATE armi.live_voice_provider_attempts
                   SET first_result_at=COALESCE(first_result_at,statement_timestamp())
                   WHERE provider_attempt_id=%s AND settled_at IS NULL""",
                (attempt_id,),
            )

    async def settle_provider_attempt(
        self,
        *,
        attempt_id: UUID,
        outcome: AttemptOutcome,
        error_code: str | None = None,
    ) -> None:
        error_code = _require_voice_error(error_code, outcome)
        async with self._factory.unit_of_work() as unit:
            result = await unit.transaction.execute(
                """UPDATE armi.live_voice_provider_attempts
                   SET dispatch_state='settled',result_status=%s,error_code=%s,
                       settled_at=statement_timestamp()
                   WHERE provider_attempt_id=%s AND settled_at IS NULL""",
                (outcome.value, error_code, attempt_id),
            )
            if result.rowcount != 1:
                raise LiveVoiceViolation(
                    "VOICE-JOURNAL-ATTEMPT", "voice attempt is closed"
                )

    async def register_fragment(
        self,
        *,
        turn_id: UUID,
        fragment_no: int,
        text: str,
    ) -> None:
        async with self._factory.unit_of_work() as unit:
            await unit.transaction.execute(
                """INSERT INTO armi.live_voice_text_fragments
                   (fragment_id,turn_id,fragment_no,body)
                   VALUES (%s,%s,%s,%s)""",
                (uuid7(), turn_id, fragment_no, text),
            )

    async def seal(self, *, turn_id: UUID) -> None:
        async with self._factory.unit_of_work() as unit:
            result = await unit.transaction.execute(
                """UPDATE armi.live_voice_turns SET registered_response_text=(
                       SELECT COALESCE(string_agg(body,'' ORDER BY fragment_no),'')
                       FROM armi.live_voice_text_fragments
                       WHERE turn_id=%s AND data_rights_redacted_at IS NULL)
                   WHERE turn_id=%s AND completed_at IS NULL""",
                (turn_id, turn_id),
            )
            if result.rowcount != 1:
                raise LiveVoiceViolation("VOICE-JOURNAL-TURN", "voice turn is closed")

    async def begin_playback(self, *, turn_id: UUID) -> UUID:
        attempt_id = uuid7()
        async with self._factory.unit_of_work() as unit:
            await unit.transaction.execute(
                """INSERT INTO armi.live_voice_playback_attempts
                   (playback_attempt_id,turn_id,dispatch_state,result_status)
                   VALUES (%s,%s,'prepared','registered')""",
                (attempt_id, turn_id),
            )
        return attempt_id

    async def mark_playback_dispatched(self, *, attempt_id: UUID) -> None:
        async with self._factory.unit_of_work() as unit:
            result = await unit.transaction.execute(
                """UPDATE armi.live_voice_playback_attempts
                   SET dispatch_state='dispatched',
                       dispatched_at=statement_timestamp()
                   WHERE playback_attempt_id=%s AND dispatch_state='prepared'
                     AND settled_at IS NULL""",
                (attempt_id,),
            )
            if result.rowcount != 1:
                raise LiveVoiceViolation(
                    "VOICE-JOURNAL-ATTEMPT", "voice attempt is closed"
                )

    async def mark_playback_first_frame(self, *, attempt_id: UUID) -> None:
        async with self._factory.unit_of_work() as unit:
            result = await unit.transaction.execute(
                """UPDATE armi.live_voice_playback_attempts
                   SET first_frame_at=COALESCE(first_frame_at,statement_timestamp())
                   WHERE playback_attempt_id=%s AND settled_at IS NULL""",
                (attempt_id,),
            )
            if result.rowcount != 1:
                raise LiveVoiceViolation(
                    "VOICE-JOURNAL-ATTEMPT", "voice attempt is closed"
                )
            await unit.transaction.execute(
                """UPDATE armi.live_voice_turns AS turn
                   SET first_audio_at=COALESCE(turn.first_audio_at,statement_timestamp()),
                       result_status='speaking'
                   FROM armi.live_voice_playback_attempts AS playback
                   WHERE playback.playback_attempt_id=%s
                     AND turn.turn_id=playback.turn_id
                     AND turn.completed_at IS NULL""",
                (attempt_id,),
            )

    async def settle_playback(
        self,
        *,
        attempt_id: UUID,
        outcome: AttemptOutcome,
        frames_written: int,
        error_code: str | None = None,
    ) -> None:
        error_code = _require_voice_error(error_code, outcome)
        if frames_written < 0 or (
            outcome is AttemptOutcome.COMPLETED and frames_written == 0
        ):
            raise LiveVoiceViolation(
                "VOICE-JOURNAL-PLAYBACK", "voice playback is invalid"
            )
        async with self._factory.unit_of_work() as unit:
            result = await unit.transaction.execute(
                """UPDATE armi.live_voice_playback_attempts
                   SET dispatch_state='settled',result_status=%s,
                       frames_written=%s,error_code=%s,
                       settled_at=statement_timestamp()
                   WHERE playback_attempt_id=%s AND settled_at IS NULL""",
                (outcome.value, frames_written, error_code, attempt_id),
            )
            if result.rowcount != 1:
                raise LiveVoiceViolation(
                    "VOICE-JOURNAL-ATTEMPT", "voice attempt is closed"
                )


class PostgreSQLLiveVoiceContextRead:
    async def completed_response_text(
        self, transaction: PostgreSQLTransaction, *, turn_id: UUID
    ) -> str | None:
        row = await (
            await transaction.execute(
                """SELECT turn.registered_response_text, turn.first_audio_at
                   FROM armi.live_voice_turns AS turn
                   WHERE turn.turn_id=%s
                     AND turn.result_status='completed'
                     AND length(turn.registered_response_text)>0
                     AND turn.playback_extent='complete'
                     AND turn.first_audio_at IS NOT NULL
                     AND EXISTS (
                         SELECT 1 FROM armi.live_voice_playback_attempts AS playback
                         WHERE playback.turn_id=turn.turn_id
                           AND playback.result_status='completed'
                     )""",
                (turn_id,),
            )
        ).fetchone()
        if row is None:
            return None
        return str(row[0])


__all__ = ("PostgreSQLLiveVoiceContextRead", "PostgreSQLLiveVoiceJournal")
