"""Bounded read projections for checks; source identities remain in the manifest."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any, cast

from .api import ContextItemCandidate

CHECK_KINDS = frozenset(
    {
        "runtime_identity",
        "current_purpose",
        "fixed_prompt",
        "self",
        "mind",
        "focus",
        "current_activity",
        "mood",
        "life_mode",
        "current_activities",
        "current_life_opportunity",
        "current_concern",
        "current_motivation",
        "recent_scene_turn",
        "capability_catalog",
    }
)


def _without_identifiers(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_identifiers(item)
            for key, item in cast(dict[str, Any], value).items()
            if key not in {"schema_kind", "source_version", "source_ref"}
            and not key.endswith(("_id", "_ids", "_ref", "_refs"))
        }
    if isinstance(value, list):
        return [_without_identifiers(item) for item in cast(list[Any], value)]
    return value


def check_context_items(
    items: list[ContextItemCandidate],
    *,
    signalled_refs: frozenset[str],
) -> list[ContextItemCandidate]:
    concerns = sorted(
        (
            item
            for item in items
            if item.item_kind in {"current_concern", "current_motivation"}
        ),
        key=lambda item: (str(item.source.reference) in signalled_refs, item.relevance),
        reverse=True,
    )
    turns = [item for item in items if item.item_kind == "recent_scene_turn"][-2:]
    selected = [
        item
        for item in items
        if item.item_kind in CHECK_KINDS
        and item.item_kind
        not in {"current_concern", "current_motivation", "recent_scene_turn"}
    ]
    selected.extend(concerns[:4])
    selected.extend(turns)
    result: list[ContextItemCandidate] = []
    open_count = len(concerns)
    for source in items:
        if source.item_kind == "mind" and source.content is not None:
            mind = json.loads(source.content)
            open_count = max(
                open_count,
                mind.get("open_concerns_count", 0)
                + mind.get("open_motivations_count", 0),
            )
    for item in selected:
        if item.content is None:
            result.append(item)
            continue
        value: Any
        try:
            value = json.loads(item.content)
        except json.JSONDecodeError:
            value = item.content
        if item.item_kind == "runtime_identity":
            value = {"identity": "same_subject"}
        elif item.item_kind == "capability_catalog":
            catalog = cast(dict[str, Any], value)
            value = {
                entry["capability_kind"]: {
                    "availability": entry["availability_status"],
                    "enabled": entry["enabled"],
                    "reason_code": entry["reason_code"],
                }
                for entry in catalog["capabilities"]
            }
        elif item.item_kind == "current_life_opportunity":
            opportunity = cast(dict[str, Any], value)
            autonomy = cast(dict[str, Any], opportunity["autonomy"])
            value = {
                key: autonomy[key]
                for key in (
                    "current_time",
                    "last_considered_at",
                    "outlet_state",
                    "outlet_bound",
                    "outlet_reason_code",
                    "last_engage",
                    "category",
                )
                if key in autonomy
            }
            value["omitted_concerns_and_motivations"] = max(
                0, open_count - min(4, len(concerns))
            )
        elif item.item_kind == "mind":
            value = {
                "assessed_objects": value["assessed_objects"],
            }
        elif item.item_kind == "self":
            value = {
                key: value[key]
                for key in ("name", "self_description", "interests", "goals")
                if key in value
            }
        elif item.item_kind == "mood":
            value = {
                key: value[key]
                for key in ("current", "active_emotions", "quality")
                if key in value
            }
        elif item.item_kind == "current_activities":
            activities = value["activities"]
            live = [
                entry
                for entry in activities
                if entry["status"] not in {"completed", "abandoned", "failed"}
            ]
            value = {
                "activities": [
                    {
                        key: entry[key]
                        for key in (
                            "status",
                            "goal",
                            "next_safe_step",
                            "waiting_condition",
                        )
                    }
                    for entry in live[:2]
                ],
                "omitted_activities": len(activities) - len(live[:2]),
            }
        elif item.item_kind == "recent_scene_turn":
            turn = cast(dict[str, Any], value)
            value = {
                "speaker": turn["speaker"],
                "text": turn["text"][:100],
                "omitted_characters": max(0, len(turn["text"]) - 100),
            }
        elif item.item_kind == "current_concern":
            concern = cast(dict[str, Any], value)
            value = {
                key: concern[key]
                for key in (
                    "question",
                    "state",
                    "consideration_reason",
                    "understanding",
                )
                if key in concern
            }
        elif item.item_kind == "current_motivation":
            motivation = cast(dict[str, Any], value)
            value = {
                key: motivation[key]
                for key in (
                    "object",
                    "domains",
                    "consideration",
                    "association",
                    "opportunity",
                )
                if key in motivation
            }
        value = _without_identifiers(value)
        # Crop values, never serialized JSON: malformed fragments hide the very
        # status/count fields that distinguish waiting from missing information.
        value = _bounded(
            value,
            text_limit=100
            if item.item_kind in {"fixed_prompt", "recent_scene_turn"}
            else 24
            if item.item_kind in {"current_concern", "current_motivation"}
            else 48,
        )
        result.append(
            replace(
                item,
                content=json.dumps(value, ensure_ascii=False, separators=(",", ":")),
            )
        )
    return result


def _bounded(value: Any, *, text_limit: int) -> Any:
    if isinstance(value, str):
        return (
            value
            if len(value) <= text_limit
            else {
                "excerpt": value[:text_limit],
                "omitted_characters": len(value) - text_limit,
            }
        )
    if isinstance(value, list):
        values = cast(list[Any], value)
        return [_bounded(item, text_limit=text_limit) for item in values[:2]] + (
            [{"omitted_items": len(values) - 2}] if len(values) > 2 else []
        )
    if isinstance(value, dict):
        return {
            key: _bounded(item, text_limit=text_limit)
            for key, item in cast(dict[str, Any], value).items()
        }
    return value
