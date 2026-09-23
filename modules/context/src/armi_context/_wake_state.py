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
    state = {
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
    return state
