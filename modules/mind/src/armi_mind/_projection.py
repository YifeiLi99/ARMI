"""Mind numeric projections exposed through the owner API."""

from datetime import datetime
from uuid import UUID

from armi_kernel.application import ConsiderationSignal

from ._state_storage import (
    numeric_mind_context_items,
    numeric_mind_projection,
    numeric_mind_signals,
)

mind_context_items = numeric_mind_context_items
mind_attention_projection = numeric_mind_projection
mind_motivation_projection = numeric_mind_projection


def mind_signals(
    payload: bytes,
    *,
    event_purpose: str | None = None,
    event_ref: UUID | None = None,
    event_at: datetime | None = None,
    activity_id: UUID | None = None,
) -> tuple[ConsiderationSignal, ...]:
    return numeric_mind_signals(payload)
