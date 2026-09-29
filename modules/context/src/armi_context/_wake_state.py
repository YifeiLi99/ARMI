"""A fixed-size projection of existing state for the read-only wake decision."""

import json
from typing import Any, cast


def wake_state(compiled: bytes) -> dict[str, Any]:
    items = [
        (item["item_kind"], json.loads(item["content"]))
        for layer in json.loads(compiled)["layers"]
        for item in layer["items"]
        if item["item_kind"]
        in {
            "mood",
            "current_motivation",
            "current_activities",
            "current_life_opportunity",
            "current_concern",
            "capability_catalog",
            "fixed_prompt",
            "mind",
        }
        and item.get("content") is not None
    ]
    by_kind = {kind: value for kind, value in items}
    mood = by_kind.get("mood", {}).get("current", {})
    motivations = [value for kind, value in items if kind == "current_motivation"]

    def peak(*path: str) -> float | None:
        known: list[float] = []
        for value in motivations:
            for key in path:
                value = (
                    cast(dict[str, Any], value).get(key)
                    if isinstance(value, dict)
                    else None
                )
            if type(value) in (int, float):
                known.append(cast(float, value))
        return round(max(known), 1) if known else None

    # These are existing owner-computed values, not new Jev appraisals. Source
    # IDs/versions stay in the Context manifest and are not paid model input.
    state: dict[str, Any] = {
        "personality_traits": by_kind.get("fixed_prompt", {}).get("traits", []),
        "assessed_objects": by_kind.get("mind", {}).get("assessed_objects"),
        "existing_motivation_count": len(motivations),
        "mood": {key: round(value, 2) for key, value in mood.items()},
        "drives": {
            "explore": peak("domains", "exploration", "motivation"),
            "adjust": peak("domains", "engagement", "adjustment"),
            "contact": peak("domains", "relatedness", "contact_need"),
            "autonomy_frustration": peak(
                "domains", "autonomy", "autonomy_frustration", "value"
            ),
            "competence_frustration": peak(
                "domains", "competence", "competence_frustration", "value"
            ),
            "relatedness_frustration": peak(
                "domains", "relatedness", "relatedness_frustration", "value"
            ),
        },
        "priority": peak("consideration", "priority"),
        "eligible": any(value["consideration"]["eligible"] for value in motivations),
        "opportunities": sorted({value["opportunity"] for value in motivations}),
        "activities": sorted(
            {
                value["status"]
                for value in by_kind.get("current_activities", {}).get("activities", [])
                if "status" in value
            }
        ),
        "outlet": by_kind.get("current_life_opportunity", {}).get("outlet_state"),
    }
    opportunity = by_kind.get("current_life_opportunity", {})
    state.update(
        {
            key: opportunity.get(key)
            for key in (
                "trigger_reasons",
                "idle_seconds",
                "last_direction",
                "last_selection_result",
            )
        }
    )
    activities = by_kind.get("current_activities", {}).get("activities", [])
    state["activities"] = [
        {
            key: value.get(key)
            for key in ("status", "goal", "next_safe_step", "waiting_condition")
        }
        for value in activities[:2]
    ]
    state["topics"] = [
        {
            key: value.get(key)
            for key in (
                "question",
                "state",
                "understanding",
                "association",
                "opportunity",
            )
            if key in value
        }
        for kind, value in items
        if kind in {"current_concern", "current_motivation"}
    ][:3]
    state["capabilities"] = by_kind.get("capability_catalog", {})
    directions = ["rest", "reflect", "explore"]
    if opportunity.get("continue_available") is True:
        directions.append("continue")
    if opportunity.get("connect_available") is True:
        directions.append("connect")
    state["available_directions"] = directions
    # Fixed priority: never crop trigger, choices or actual unknown state.
    # Optional descriptions yield space before required selection facts.
    while len(json.dumps(state, ensure_ascii=False).encode()) > 2400:
        if len(state["topics"]) > 1:
            state["topics"].pop()
        elif len(state["activities"]) > (
            1 if "activity_due" in (state["trigger_reasons"] or []) else 0
        ):
            state["activities"].pop()
        elif state["capabilities"]:
            state["capabilities"].pop(next(reversed(state["capabilities"])))
        else:
            break
    return state
