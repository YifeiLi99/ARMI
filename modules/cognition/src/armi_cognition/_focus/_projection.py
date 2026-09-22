"""Cognition-owned focus read models."""

import json
from datetime import datetime
from uuid import UUID

from armi_kernel.application import ConsiderationSignal, PsychologicalContextItem

from ._concerns import CONCERN_RECORDS, concern_attention_status, concern_signals


def focus_context_items(
    payload: bytes,
    *,
    revision_id: UUID,
    version: int,
    as_of: datetime,
    purpose: str,
    signals: tuple[ConsiderationSignal, ...] = (),
    related_object_refs: frozenset[UUID] = frozenset(),
) -> tuple[PsychologicalContextItem, ...]:
    records = CONCERN_RECORDS.validate_json(
        json.dumps(json.loads(payload)["concerns"]), strict=True
    )
    due = {s.object_ref for s in signals if s.owner == "focus"}
    selected = sorted(
        (r for r in records if r.state in {"open", "waiting"}),
        key=lambda r: (
            r.concern_id not in related_object_refs,
            r.concern_id not in due,
            r.review_at or datetime.max.replace(tzinfo=as_of.tzinfo),
            r.updated_at,
            str(r.concern_id),
        ),
    )[:4]
    result = [
        PsychologicalContextItem(
            "focus",
            "focus",
            revision_id,
            version,
            json.dumps(
                {
                    "schema_kind": "armi.focus",
                    "active_count": sum(
                        r.state in {"open", "waiting"} for r in records
                    ),
                }
            ),
            purpose != "consider_other_human_input",
            90,
        )
    ]
    for record in selected:
        value = record.model_dump(mode="json")
        value["elapsed_seconds"] = max(
            0, int((as_of - record.updated_at).total_seconds())
        )
        value["consideration_reason"] = next(
            (s.reason for s in signals if s.object_ref == record.concern_id),
            "ongoing_concern",
        )
        result.append(
            PsychologicalContextItem(
                "current_concern",
                "cognition_focus",
                record.concern_id,
                version,
                json.dumps(value, ensure_ascii=False),
                True,
                95,
            )
        )
    return tuple(result)


def focus_editable_state(payload: bytes) -> bytes:
    return payload


def focus_attention_projection(
    payload: bytes, *, as_of: datetime, consumed: frozenset[tuple[str, str, str]]
) -> list[dict[str, object]]:
    return concern_attention_status(
        CONCERN_RECORDS.validate_json(
            json.dumps(json.loads(payload)["concerns"]), strict=True
        ),
        as_of=as_of,
        consumed=consumed,
    )


def focus_signals(
    payload: bytes,
    *,
    event_purpose: str | None = None,
    event_ref: UUID | None = None,
    event_at: datetime | None = None,
    activity_id: UUID | None = None,
) -> tuple[ConsiderationSignal, ...]:
    return concern_signals(
        CONCERN_RECORDS.validate_json(
            json.dumps(json.loads(payload)["concerns"]), strict=True
        ),
        event_purpose=event_purpose,
        event_ref=event_ref,
        event_at=event_at,
        activity_id=activity_id,
    )
