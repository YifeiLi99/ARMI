"""Transport serialization of the shared Creator system application."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, cast

from armi_runtime.application.creator_system import (
    CreatorSystem,
    CreatorSystemViolation,
)
from armi_runtime.application.interaction import InteractionResult

from .creator_http import _rejected, _unavailable

SYSTEM_COMMANDS = frozenset(
    {
        "health_live",
        "health_ready",
        "runtime_status",
        "channel_start",
        "channel_stop",
        "channel_status",
        "voice_start",
        "voice_stop",
        "voice_status",
        "vision_start",
        "vision_stop",
        "vision_status",
        "vision_observe",
        "vision_observation",
        "vision_preview",
    }
)


async def invoke_system(
    system: CreatorSystem, operation: str, arguments: Mapping[str, object]
) -> InteractionResult:
    try:
        if operation == "health_live":
            return InteractionResult("returned", {"status": "alive"})
        if operation == "health_ready":
            status = system.readiness().value
            return InteractionResult(
                "returned" if status == "ready" else "unavailable",
                {"status": status},
                200 if status == "ready" else 503,
            )
        if operation == "runtime_status":
            return InteractionResult(
                "returned", system.runtime_status().model_dump(mode="json")
            )
        action = cast(Literal["start", "stop", "status"], operation.rsplit("_", 1)[-1])
        if operation in {"channel_start", "channel_stop", "channel_status"}:
            return InteractionResult(
                "returned", (await system.channel(action)).model_dump(mode="json")
            )
        if operation in {"voice_start", "voice_stop", "voice_status"}:
            return InteractionResult(
                "returned", (await system.voice(action)).model_dump(mode="json")
            )
        if operation in {"vision_start", "vision_stop", "vision_status"}:
            return InteractionResult(
                "returned",
                (
                    await system.vision(
                        action, cast(str | None, arguments.get("source_kind"))
                    )
                ).model_dump(mode="json"),
            )
        if operation == "vision_observe":
            observation = await system.observe(
                str(arguments["source_kind"]), str(arguments.get("idempotency_key", ""))
            )
            status = (
                202
                if observation.status
                in {"capture_pending", "capturing", "registered", "recognizing"}
                else 200
            )
            return InteractionResult(
                "returned", observation.model_dump(mode="json"), status
            )
        if operation == "vision_observation":
            return InteractionResult(
                "returned",
                (await system.observation(str(arguments["observation_id"]))).model_dump(
                    mode="json"
                ),
            )
        if operation == "vision_preview":
            content = await system.preview(str(arguments["source_kind"]))
            return InteractionResult(
                "returned", {}, content=content, media_type="image/jpeg"
            )
        raise CreatorSystemViolation("INPUT_INTERACTION_OPERATION_UNKNOWN", 400)
    except CreatorSystemViolation as error:
        return InteractionResult(
            "unavailable" if error.status_code >= 500 else "rejected",
            _unavailable(error.code)
            if error.code.startswith("DEPENDENCY_")
            else _rejected(error.code),
            error.status_code,
        )


__all__ = ("SYSTEM_COMMANDS", "invoke_system")
