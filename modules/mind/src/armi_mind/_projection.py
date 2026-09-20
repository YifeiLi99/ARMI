"""Mind-owned read models. Consumers never interpret persistent concern records."""

from __future__ import annotations

import json
from datetime import datetime
from uuid import UUID

import rfc8785
from armi_kernel.application import ConsiderationSignal, PsychologicalContextItem

from ._concerns import CONCERN_RECORDS, concern_attention_status, concern_signals
from ._motivation import MOTIVATION_RECORDS, motivation_signals, motivation_view


def mind_context_items(
    payload: bytes,
    *,
    revision_id: UUID,
    version: int,
    as_of: datetime,
    purpose: str,
    signals: tuple[ConsiderationSignal, ...] = (),
    related_object_refs: frozenset[UUID] = frozenset(),
) -> tuple[PsychologicalContextItem, ...]:
    document = json.loads(payload)
    records = CONCERN_RECORDS.validate_json(
        json.dumps(document.pop("concerns")), strict=True
    )
    motivations = MOTIVATION_RECORDS.validate_json(
        json.dumps(document.pop("motivation_states")), strict=True
    )
    if purpose == "consider_autonomy_check":
        document["open_concerns_count"] = sum(
            c.state in {"open", "waiting"} for c in records
        )
        document["open_motivations_count"] = sum(
            m.parameters.resolution == "open" for m in motivations
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
    # This is a per-context attention window, never a persistent record cap.
    # Explicit object links come first; autonomous review rotates unconsumed due
    # signals ahead of recency. See DESIGN.md: persistent motivation selection.
    autonomous = purpose in {"consider_autonomous_life", "consider_autonomy_check"}
    selected = sorted(
        (m for m in motivations if m.parameters.resolution == "open"),
        key=lambda m: (
            m.object_id in related_object_refs,
            autonomous and m.motivation_id in reasons,
            m.anchor_at,
            m.motivation_id.int,
        ),
        reverse=True,
    )[:4]
    for motivation in selected:
        content = motivation_view(motivation, as_of=as_of)
        content["consideration_reason"] = reasons.get(
            motivation.motivation_id, "ongoing_motivation"
        )
        result.append(
            PsychologicalContextItem(
                "current_motivation",
                "mind_motivation",
                motivation.motivation_id,
                version,
                json.dumps(content, ensure_ascii=False),
                False,
                95 if motivation.object_id in related_object_refs else 85,
            )
        )
    return tuple(result)


def mind_editable_state(payload: bytes) -> bytes:
    document = json.loads(payload)
    document.pop("concerns", None)
    document.pop("motivation_states", None)
    return rfc8785.dumps(document)


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


def mind_motivation_projection(
    payload: bytes,
    *,
    as_of: datetime,
    consumed: frozenset[tuple[str, str, str]],
) -> list[dict[str, object]]:
    document = json.loads(payload)
    motivations = MOTIVATION_RECORDS.validate_json(
        json.dumps(document["motivation_states"]), strict=True
    )
    return [
        {
            **motivation_view(r, as_of=as_of),
            "condition_state": "consumed"
            if ("mind", str(r.motivation_id), str(r.source_commit_id)) in consumed
            else "waiting_for_event"
            if r.review_at is None
            else "due"
            if r.review_at <= as_of
            else "scheduled",
        }
        for r in motivations
        if r.parameters.resolution == "open"
    ]


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
    ) + motivation_signals(
        MOTIVATION_RECORDS.validate_json(
            json.dumps(document["motivation_states"]), strict=True
        )
    )
