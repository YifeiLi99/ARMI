from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid7

import pytest
from armi_live_voice._application import PostgreSQLLiveVoiceJournal
from armi_live_voice._recovery import LiveVoiceRecoveryParticipant
from armi_live_voice.api import (
    LiveVoiceBinding,
    VoiceProviderBinding,
    VoiceProviderService,
)
from armi_runtime_foundation import RecoveryScope


class _UnitOfWork:
    def __init__(self, transaction: AsyncMock) -> None:
        self.transaction = transaction

    async def __aenter__(self) -> _UnitOfWork:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None


class _Factory:
    def __init__(self, transaction: AsyncMock) -> None:
        self._transaction = transaction

    def unit_of_work(self) -> _UnitOfWork:
        return _UnitOfWork(self._transaction)


def _binding() -> LiveVoiceBinding:
    return LiveVoiceBinding(
        "Windows WASAPI",
        "microphone",
        "Windows WASAPI",
        "speaker",
        VoiceProviderBinding(VoiceProviderService.ASR, "volcengine", "asr"),
        VoiceProviderBinding(
            VoiceProviderService.LLM, "ark", "model-resource", "model-identity"
        ),
        VoiceProviderBinding(VoiceProviderService.TTS, "volcengine", "tts", "voice"),
    )


@pytest.mark.asyncio
async def test_turn_binds_model_and_first_playback_marks_turn() -> None:
    result = AsyncMock()
    result.rowcount = 1
    transaction = AsyncMock()
    transaction.execute.return_value = result
    journal = PostgreSQLLiveVoiceJournal(
        factory=_Factory(transaction),  # type: ignore[arg-type]
        subject_id=uuid7(),
        creator_party_id=uuid7(),
        scene_id=uuid7(),
        binding=_binding(),
    )

    await journal.begin_turn(
        session_id=uuid7(), turn_id=uuid7(), turn_no=1, context_version="ctx:1"
    )
    attempt_id = uuid7()
    await journal.mark_playback_first_frame(attempt_id=attempt_id)

    begin_parameters = transaction.execute.await_args_list[0].args[1]
    assert begin_parameters[3] == "model-identity"
    assert "first_audio_at" in transaction.execute.await_args_list[2].args[0]
    assert transaction.execute.await_args_list[2].args[1] == (attempt_id,)


@pytest.mark.asyncio
async def test_recovery_terminalizes_attempts_turns_then_session() -> None:
    result_sets = []
    for row in (uuid7(), uuid7(), uuid7(), uuid7()):
        result = AsyncMock()
        result.fetchall.return_value = ((row,),)
        result_sets.append(result)
    transaction = AsyncMock()
    transaction.execute.side_effect = result_sets
    scope = RecoveryScope(uuid7(), uuid7(), uuid7(), uuid7(), uuid7(), 1)

    contribution = await LiveVoiceRecoveryParticipant().recover(
        transaction, scope, ()
    )

    statements = [call.args[0] for call in transaction.execute.await_args_list]
    assert "provider_attempts" in statements[0]
    assert "playback_attempts" in statements[1]
    assert "live_voice_turns" in statements[2]
    assert "live_voice_sessions" in statements[3]
    assert [metric.value for metric in contribution.metrics] == [1, 1, 1, 1]
    assert contribution.findings[0].kind == "live_voice_session"
