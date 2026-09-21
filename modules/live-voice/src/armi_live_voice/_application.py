"""Short-transaction PostgreSQL owner for one live-voice session."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import datetime
from typing import Literal, cast
from uuid import UUID

from armi_interaction.api import ExternalMessageViolation
from armi_kernel.application import ProviderCallReceipt
from armi_runtime_foundation import (
    PostgreSQLRuntimeUnitOfWorkFactory,
    PostgreSQLTransaction,
)

from .api import (
    AttemptOutcome,
    LiveVoiceBinding,
    LiveVoiceSessionState,
    LiveVoiceViolation,
    PlaybackExtent,
    VoiceActivityState,
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
        "_activity",
        "_binding",
        "_creator_party_id",
        "_factory",
        "_playback_diagnostic",
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
        activity: VoiceActivityState | None = None,
        playback_diagnostic: Callable[[str, UUID, int, str | None], None] | None = None,
    ) -> None:
        if any(
            type(value) is not UUID or value.version != 7
            for value in (subject_id, creator_party_id, scene_id)
        ):
            raise LiveVoiceViolation("VOICE-JOURNAL-SCOPE", "voice scope is invalid")
        self._activity = activity if activity is not None else VoiceActivityState()
        self._factory = factory
        self._subject_id = subject_id
        self._creator_party_id = creator_party_id
        self._scene_id = scene_id
        self._binding = binding
        self._timeline = timeline
        self._playback_diagnostic = playback_diagnostic

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

    def _require_session(self, session_id: UUID) -> None:
        if self._activity.session_id != session_id:
            raise LiveVoiceViolation("VOICE-JOURNAL-STATE", "voice session is closed")

    async def open_session(self, *, session_id: UUID) -> None:
        if self._activity.session_id is not None:
            raise LiveVoiceViolation(
                "VOICE-JOURNAL-STATE", "voice session is already open"
            )
        self._activity.session_id = session_id
        logging.getLogger(__name__).info(
            "voice.session.opened",
            extra={
                "session_id": str(session_id),
                "scene_id": str(self._scene_id),
                "input_host_api": self._binding.input_host_api,
                "input_device_name": self._binding.input_device_name,
                "output_host_api": self._binding.output_host_api,
                "output_device_name": self._binding.output_device_name,
            },
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
        self._require_session(session_id)
        logging.getLogger(__name__).info(
            "voice.session.state",
            extra={
                "session_id": str(session_id),
                "voice_state": state.value,
                "context_version": context_version,
            },
        )

    async def close_session(
        self, *, session_id: UUID, error_code: str | None = None
    ) -> None:
        if error_code is not None:
            _require_voice_error(error_code, AttemptOutcome.FAILED)
        if self._activity.session_id != session_id:
            return
        # Clear before awaiting storage: a failed receipt cannot leave a phantom microphone.
        self._activity.session_id = None
        logging.getLogger(__name__).info(
            "voice.session.closed",
            extra={
                "session_id": str(session_id),
                "error_code": error_code,
            },
        )
        async with self._factory.unit_of_work() as unit:
            await self._timeline.record_voice_session_end(
                unit.transaction, scene_id=self._scene_id, session_id=session_id
            )

    async def begin_turn(
        self,
        *,
        session_id: UUID,
        turn_id: UUID,
        turn_no: int,
        context_version: str,
    ) -> None:
        self._require_session(session_id)
        async with self._factory.unit_of_work() as unit:
            self._require_session(session_id)
            result = await unit.transaction.execute(
                """INSERT INTO armi.live_voice_turns
                   (turn_id,session_id,turn_no,model_identity,context_version,
                    result_status,subject_id,creator_party_id,scene_id)
                   SELECT %s,%s,%s,%s,%s,'recognizing',%s,%s,%s
                   WHERE NOT EXISTS (SELECT 1 FROM armi.live_voice_turns
                     WHERE session_id=%s AND data_rights_redacted_at IS NOT NULL)""",
                (
                    turn_id,
                    session_id,
                    turn_no,
                    self._binding.llm.model_identity,
                    context_version,
                    self._subject_id,
                    self._creator_party_id,
                    self._scene_id,
                    session_id,
                ),
            )
            if result.rowcount != 1:
                raise LiveVoiceViolation(
                    "VOICE-DATA-RIGHTS-CANCELLED", "voice session is redacted"
                )

    async def record_transcript(
        self,
        *,
        turn_id: UUID,
        transcript: str | None,
        interaction_id: UUID | None,
        opportunity_id: UUID | None,
    ) -> None:
        async with self._factory.unit_of_work() as unit:
            result = await unit.transaction.execute(
                """UPDATE armi.live_voice_turns
                   SET final_transcript=%s,interaction_id=%s,root_opportunity_id=%s,
                       speech_ended_at=statement_timestamp(),result_status='thinking'
                   WHERE turn_id=%s AND completed_at IS NULL
                     AND data_rights_redacted_at IS NULL""",
                (transcript, interaction_id, opportunity_id, turn_id),
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
            response = await (
                await unit.transaction.execute(
                    "SELECT registered_response_text,playback_extent,frames_written "
                    "FROM armi.live_voice_turns WHERE turn_id=%s FOR UPDATE",
                    (turn_id,),
                )
            ).fetchone()
            if response is None:
                raise LiveVoiceViolation("VOICE-JOURNAL-TURN", "voice turn is absent")
            extent, frames_written = str(response[1]), int(response[2])
            if extent == "complete":
                status, error_code = "completed", None
            elif extent == "partial_prefix":
                status = "partial"
            elif extent == "unknown_completion":
                status = "unknown"
                error_code = error_code or "VOICE-PLAYBACK-RESULT-UNKNOWN"
            result = await unit.transaction.execute(
                """UPDATE armi.live_voice_turns
                   SET result_status=%s,
                       playback_extent=%s,frames_written=%s,error_code=%s,
                       completed_at=statement_timestamp()
                   WHERE turn_id=%s AND completed_at IS NULL
                   RETURNING first_audio_at""",
                (status, extent, frames_written, error_code, turn_id),
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

    async def record_provider_call(
        self,
        *,
        turn_id: UUID | None,
        session_id: UUID | None,
        receipt: ProviderCallReceipt,
    ) -> None:
        if (turn_id is None) == (session_id is None):
            raise LiveVoiceViolation(
                "VOICE-JOURNAL-USAGE", "exactly one parent is required"
            )
        # Keep consumption with its owner, including late receipts after interruption.
        # Only registration requires an open parent; see DESIGN.md.
        parameters = (
            receipt.call_id,
            json.dumps(receipt.document()),
            turn_id if turn_id is not None else session_id,
            receipt.registration,
            receipt.call_id,
            receipt.registration,
            receipt.call_id,
        )
        async with self._factory.provider_usage_unit_of_work(receipt=receipt) as unit:
            if turn_id is not None:
                result = await unit.transaction.execute(
                    """UPDATE armi.live_voice_turns
                       SET provider_calls=jsonb_set(provider_calls,ARRAY[%s],%s::jsonb)
                       WHERE turn_id=%s
                         AND ((%s AND completed_at IS NULL AND data_rights_redacted_at IS NULL
                              AND NOT (provider_calls ? %s))
                              OR (NOT %s AND provider_calls ? %s))""",
                    parameters,
                )
            else:
                assert session_id is not None
                if receipt.registration:
                    self._require_session(session_id)
                try:
                    await self._timeline.record_voice_provider_call(
                        unit.transaction,
                        scene_id=self._scene_id,
                        session_id=session_id,
                        receipt=receipt,
                    )
                except ExternalMessageViolation as error:
                    raise LiveVoiceViolation(
                        "VOICE-JOURNAL-USAGE",
                        "usage parent or registration is unavailable",
                    ) from error
                return
            if result.rowcount != 1:
                raise LiveVoiceViolation(
                    "VOICE-JOURNAL-USAGE", "usage parent or registration is unavailable"
                )

    async def register_fragment(
        self,
        *,
        turn_id: UUID,
        fragment_no: int,
        text: str,
    ) -> None:
        if (
            type(fragment_no) is not int
            or not 1 <= fragment_no <= 64
            or not 1 <= len(text.strip()) <= 160
            or "\x00" in text
        ):
            raise LiveVoiceViolation(
                "VOICE-JOURNAL-FRAGMENT", "voice fragment is invalid"
            )
        async with self._factory.unit_of_work() as unit:
            # One atomic append keeps order and rejects duplicate fragments (DESIGN.md).
            result = await unit.transaction.execute(
                """UPDATE armi.live_voice_turns
                   SET registered_response_text=registered_response_text || %s,
                       response_fragment_count=%s
                   WHERE turn_id=%s AND response_fragment_count=%s
                     AND completed_at IS NULL AND data_rights_redacted_at IS NULL
                     AND registered_response_text IS NOT NULL""",
                (text, fragment_no, turn_id, fragment_no - 1),
            )
            if result.rowcount != 1:
                raise LiveVoiceViolation(
                    "VOICE-JOURNAL-FRAGMENT",
                    "voice fragment is out of sequence or turn is closed",
                )

    def _log_playback(
        self, event: str, turn_id: UUID, frames: int = 0, error: str | None = None
    ) -> None:
        if self._playback_diagnostic is not None:
            self._playback_diagnostic(event, turn_id, frames, error)

    async def mark_playback_dispatched(self, *, turn_id: UUID) -> None:
        async with self._factory.unit_of_work() as unit:
            # Record uncertainty before device I/O; a crash must never imply no sound.
            result = await unit.transaction.execute(
                """UPDATE armi.live_voice_turns
                   SET playback_extent='unknown_completion',result_status='speaking'
                   WHERE turn_id=%s AND result_status='thinking'
                     AND playback_extent='none' AND completed_at IS NULL
                     AND data_rights_redacted_at IS NULL""",
                (turn_id,),
            )
            if result.rowcount != 1:
                raise LiveVoiceViolation(
                    "VOICE-JOURNAL-PLAYBACK", "voice playback is closed"
                )
        self._log_playback("dispatched", turn_id)

    async def mark_playback_first_frame(self, *, turn_id: UUID) -> None:
        async with self._factory.unit_of_work() as unit:
            result = await unit.transaction.execute(
                """UPDATE armi.live_voice_turns
                   SET first_audio_at=statement_timestamp(),frames_written=1
                   WHERE turn_id=%s AND result_status='speaking'
                     AND playback_extent='unknown_completion'
                     AND first_audio_at IS NULL AND completed_at IS NULL""",
                (turn_id,),
            )
            if result.rowcount != 1:
                raise LiveVoiceViolation(
                    "VOICE-JOURNAL-PLAYBACK", "voice playback is closed"
                )
        self._log_playback("first_frame", turn_id, 1)

    async def settle_playback(
        self,
        *,
        turn_id: UUID,
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
        extent = {
            AttemptOutcome.COMPLETED: "complete",
            AttemptOutcome.PARTIAL: "partial_prefix",
            AttemptOutcome.UNKNOWN: "unknown_completion",
        }.get(outcome, "none")
        status = "failed" if outcome is AttemptOutcome.CANCELLED else outcome.value
        async with self._factory.unit_of_work() as unit:
            result = await unit.transaction.execute(
                """UPDATE armi.live_voice_turns
                   SET playback_extent=%s,result_status=%s,
                       frames_written=%s,error_code=%s
                   WHERE turn_id=%s AND result_status='speaking'
                     AND playback_extent='unknown_completion'
                     AND completed_at IS NULL
                     AND (%s <> 'complete' OR first_audio_at IS NOT NULL)""",
                (extent, status, frames_written, error_code, turn_id, extent),
            )
            if result.rowcount != 1:
                raise LiveVoiceViolation(
                    "VOICE-JOURNAL-PLAYBACK", "voice playback is closed"
                )
        self._log_playback(outcome.value, turn_id, frames_written, error_code)


class PostgreSQLLiveVoiceContextRead:
    async def completed_playback(
        self, transaction: PostgreSQLTransaction, *, turn_id: UUID
    ) -> tuple[UUID, str, datetime] | None:
        row = await (
            await transaction.execute(
                """SELECT turn_id,registered_response_text,first_audio_at
                   FROM armi.live_voice_turns
                   WHERE turn_id=%s AND playback_extent='complete'
                     AND first_audio_at IS NOT NULL
                     AND data_rights_redacted_at IS NULL""",
                (turn_id,),
            )
        ).fetchone()
        return None if row is None else (row[0], str(row[1]), row[2])

    async def turn_for_opportunity(
        self, transaction: PostgreSQLTransaction, *, opportunity_id: UUID
    ) -> UUID | None:
        row = await (
            await transaction.execute(
                "SELECT turn_id FROM armi.live_voice_turns WHERE root_opportunity_id=%s",
                (opportunity_id,),
            )
        ).fetchone()
        return None if row is None else row[0]

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
                     AND turn.first_audio_at IS NOT NULL""",
                (turn_id,),
            )
        ).fetchone()
        if row is None:
            return None
        return str(row[0])


__all__ = ("PostgreSQLLiveVoiceContextRead", "PostgreSQLLiveVoiceJournal")
