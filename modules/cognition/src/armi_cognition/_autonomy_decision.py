"""Local scheduling from frozen owner signals; never a subjective decision."""

import json


def should_consider_autonomy(context: bytes) -> bool:
    document = json.loads(context)
    for layer in document["layers"]:
        for item in layer["items"]:
            kind = item["item_kind"]
            if kind == "current_activity":
                return True
            if kind not in {"current_motivation", "current_concern"}:
                continue
            value = json.loads(item["content"])
            if kind == "current_motivation" and value["consideration"]["eligible"]:
                return True
            if kind == "current_concern" and value["consideration_reason"] in {
                "review_time_reached",
                "creator_input",
                "activity_result",
            }:
                return True
    return False
