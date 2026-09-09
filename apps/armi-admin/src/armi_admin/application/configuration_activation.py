"""Compare saved configuration with evidence from its actual consumers."""

from typing import Any


def runtime_activation(
    runtime: dict[str, Any], desired: dict[str, Any]
) -> dict[str, Any]:
    running = runtime.get("runtime", {})
    actual = running.get("runtime_configuration_digest")
    blocked = [
        item
        for item in running.get("configuration_overrides", [])
        if desired["effective_on_next_start"][item["path"][0]][item["path"][1]]
        != item["value"]
    ]
    activation = (
        "not_running"
        if runtime.get("status") == "stopped"
        else "effective"
        if actual is not None and actual == desired["desired_digest"]
        else "environment_override"
        if blocked
        else "restart_required"
        if actual is not None
        else "not_verified"
    )
    return {
        "activation": activation,
        "restart_required": activation == "restart_required",
        "running_digest": actual,
        "running_sources": running.get("configuration_sources", []),
        "blocking_overrides": blocked,
    }


def asset_activation(
    runtime: dict[str, Any], target: str, desired_version: str | None
) -> dict[str, Any]:
    loaded = runtime.get("runtime", {}).get("configuration_assets", {}).get(target, {})
    versions = loaded.get("versions", [])
    activation = (
        "not_running"
        if runtime.get("status") == "stopped"
        else "effective"
        if desired_version is not None and versions == [desired_version]
        else "partially_effective"
        if desired_version is not None and desired_version in versions
        else "restart_required"
        if versions
        else "not_verified"
    )
    return {
        "activation": activation,
        "restart_required": activation in {"restart_required", "partially_effective"},
        "loaded": loaded,
    }


__all__ = ("asset_activation", "runtime_activation")
