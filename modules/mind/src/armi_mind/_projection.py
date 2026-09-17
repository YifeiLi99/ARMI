"""Mind-owned read models. Consumers never interpret persistent concern records."""

from __future__ import annotations

import json
from datetime import datetime
from uuid import UUID

from armi_kernel.application import ConsiderationSignal, PsychologicalContextItem

from ._concerns import CONCERN_RECORDS, concern_attention_status, concern_signals


def mind_context_items(
    payload: bytes,
    *,
    revision_id: UUID,
    version: int,
    as_of: datetime,
    purpose: str,
    signals: tuple[ConsiderationSignal, ...] = (),
) -> tuple[PsychologicalContextItem, ...]:
    document = json.loads(payload)
    records = CONCERN_RECORDS.validate_json(
        json.dumps(document.pop("concerns")), strict=True
    )
    result = [
        PsychologicalContextItem(
            "mind",
            "mind",
            revision_id,
            version,
            json.dumps(document, ensure_ascii=False),
            purpose != "consider_other_human_input",
            90,
        )
    ]
    reasons = {
        signal.object_ref: signal.reason for signal in signals if signal.owner == "mind"
    }
    for concern in records:
        if concern.state not in {"open", "waiting"}:
            continue
        content = concern.model_dump(mode="json")
        content["elapsed_seconds"] = max(
            0, int((as_of - concern.updated_at).total_seconds())
        )
        content["consideration_reason"] = reasons.get(
            concern.concern_id, "ongoing_concern"
        )
        result.append(
            PsychologicalContextItem(
                "current_concern",
                "mind_concern",
                concern.concern_id,
                version,
                json.dumps(content, ensure_ascii=False),
                True,
                95,
            )
        )
    return tuple(result)


def mind_editable_state(payload: bytes) -> bytes:
    document = json.loads(payload)
    document.pop("concerns", None)
    return json.dumps(document, ensure_ascii=False).encode("utf-8")


__all__ = ("mind_context_items", "mind_editable_state")


def mind_attention_projection(
    payload: bytes,
    *,
    as_of: datetime,
    consumed: frozenset[tuple[str, str, str]],
) -> list[dict[str, object]]:
    document = json.loads(payload)
    records = CONCERN_RECORDS.validate_json(
        json.dumps(document["concerns"]), strict=True
    )
    return concern_attention_status(records, as_of=as_of, consumed=consumed)


def mind_signals(
    payload: bytes,
    *,
    event_purpose: str | None = None,
    event_ref: UUID | None = None,
    event_at: datetime | None = None,
    activity_id: UUID | None = None,
) -> tuple[ConsiderationSignal, ...]:
    document = json.loads(payload)
    return concern_signals(
        CONCERN_RECORDS.validate_json(json.dumps(document["concerns"]), strict=True),
        event_purpose=event_purpose,
        event_ref=event_ref,
        event_at=event_at,
        activity_id=activity_id,
    )
