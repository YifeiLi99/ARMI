"""Bind owner reference choices to the frozen Context, before provider adaptation."""

from copy import deepcopy
from typing import Any, cast


def bind_context_schema(
    schema: dict[str, Any],
    refs: tuple[dict[str, object], ...],
) -> dict[str, Any]:
    result = deepcopy(schema)
    definitions = result.get("$defs", {})
    blocked: set[str] = set()
    for name, field, kind in (
        ("ExistingAppraisal", "episode_ref", "active_affective_episode"),
        ("UpdateConcern", "concern_ref", "current_concern"),
        ("CloseConcern", "concern_ref", "current_concern"),
        ("ActivityReview", "activity_ref", "current_activity"),
    ):
        if name not in definitions:
            continue
        allowed = [item["ref"] for item in refs if item["item_kind"] == kind]
        if not allowed:
            blocked.add(name)
        else:
            definitions[name]["properties"][field] = {"type": "string", "enum": allowed}

    def prune(value: Any) -> None:
        if isinstance(value, list):
            for child in cast(list[Any], value):
                prune(child)
        elif isinstance(value, dict):
            node = cast(dict[str, Any], value)
            for union in ("oneOf", "anyOf"):
                if union in node:
                    node[union] = [
                        branch
                        for branch in node[union]
                        if branch.get("$ref", "").rsplit("/", 1)[-1] not in blocked
                    ]
            if "discriminator" in node:
                mapping = node["discriminator"].get("mapping", {})
                node["discriminator"]["mapping"] = {
                    key: ref
                    for key, ref in mapping.items()
                    if ref.rsplit("/", 1)[-1] not in blocked
                }
            for child in node.values():
                prune(child)

    for name in blocked:
        del definitions[name]
    prune(result)
    return result
