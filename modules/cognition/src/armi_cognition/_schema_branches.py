"""Express cross-field candidate shapes in the schema sent to the model."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def object_branches(
    schema: dict[str, Any], overrides: list[dict[str, Any]]
) -> dict[str, Any]:
    definitions = schema.get("$defs")
    branches: list[dict[str, Any]] = []
    for properties in overrides:
        branch = deepcopy(
            {key: value for key, value in schema.items() if key != "$defs"}
        )
        branch["properties"].update(properties)
        branches.append(branch)
    result: dict[str, Any] = {"anyOf": branches}
    if definitions is not None:
        result["$defs"] = definitions
    return result


def non_null(schema: dict[str, Any]) -> dict[str, Any]:
    alternatives = [item for item in schema["anyOf"] if item.get("type") != "null"]
    return alternatives[0] if len(alternatives) == 1 else {"anyOf": alternatives}
