"""Combine process-local microphone ownership with durable scene activity."""

from datetime import datetime
from uuid import UUID

from armi_interaction.api import last_voice_activity
from armi_runtime_foundation import PostgreSQLTransaction

from .api import VoiceActivityState


async def voice_activity(
    transaction: PostgreSQLTransaction,
    *,
    subject_id: UUID,
    activity: VoiceActivityState | None = None,
) -> tuple[bool, datetime | None]:
    ended_at = await last_voice_activity(transaction, subject_id=subject_id)
    return activity is not None and activity.session_id is not None, ended_at
