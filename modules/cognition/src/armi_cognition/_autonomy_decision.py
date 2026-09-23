"""Local scheduling from frozen owner signals; never a subjective decision."""

import json

from armi_kernel.application import record_diagnostic


def should_consider_autonomy(context: bytes) -> bool:
    document = json.loads(context)
    activity_count = concern_count = motivation_count = 0
    for layer in document["layers"]:
        for item in layer["items"]:
            kind = item["item_kind"]
            if kind == "current_activity":
                activity_count += 1
            if kind not in {"current_motivation", "current_concern"}:
                continue
            value = json.loads(item["content"])
            if kind == "current_motivation" and value["consideration"]["eligible"]:
                motivation_count += 1
            if kind == "current_concern" and value["consideration_reason"] in {
                "review_time_reached",
                "creator_input",
                "activity_result",
            }:
                concern_count += 1
    engage = bool(activity_count or concern_count or motivation_count)
    record_diagnostic(
        "autonomy.check.evaluated",
        component="cognition",
        outcome="eligible" if engage else "not_scheduled",
        reason="owner_signal_available" if engage else "no_eligible_owner_signal",
        activity_count=activity_count,
        eligible_concern_count=concern_count,
        eligible_motivation_count=motivation_count,
    )
    return engage
