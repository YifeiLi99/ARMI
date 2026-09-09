"""Public system failures retain business semantics across transport projection."""

from typing import cast
from unittest.mock import AsyncMock, Mock

import pytest
from armi_live_vision.api import LiveVisionViolation
from armi_runtime.application.creator_system import CreatorSystem
from armi_runtime.interfaces.system_commands import invoke_system


@pytest.fixture
def system() -> CreatorSystem:
    return CreatorSystem(
        readiness=Mock(),
        runtime_status=Mock(),
        qq_health=AsyncMock(),
        qq_control=None,
        voice_control=None,
        vision_control=AsyncMock(),
        vision_observe=AsyncMock(),
        vision_observation=AsyncMock(return_value=None),
        vision_preview=Mock(return_value=None),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "identity", ["invalid", "018f3f4a-7b8c-7def-8abc-1234567890ab"]
)
async def test_missing_observation_is_a_public_not_found(
    system: CreatorSystem, identity: str
) -> None:
    result = await invoke_system(
        system, "vision_observation", {"observation_id": identity}
    )
    assert result.status_code == 404
    assert (
        cast(dict[str, object], result.payload["error"])["code"]
        == "INPUT_VISION_NOT_FOUND"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("code", "status", "public_code"),
    [
        ("VISION-SOURCE-KIND", 400, "INPUT_VISION_SOURCE_KIND"),
        ("VISION-IDEMPOTENCY-CONFLICT", 409, "IDEMPOTENCY_VISION_CONFLICT"),
        ("VISION-SOURCE-NOT-RUNNING", 503, "DEPENDENCY_VISION_SOURCE_NOT_RUNNING"),
    ],
)
async def test_owner_vision_failure_is_a_valid_public_outcome(
    system: CreatorSystem, code: str, status: int, public_code: str
) -> None:
    cast(AsyncMock, system.vision_control).side_effect = LiveVisionViolation(
        code, "owner detail"
    )
    result = await invoke_system(system, "vision_start", {"source_kind": "camera"})
    assert result.status_code == status
    assert cast(dict[str, object], result.payload["error"])["code"] == public_code


@pytest.mark.asyncio
async def test_invalid_observation_key_is_input_failure(system: CreatorSystem) -> None:
    result = await invoke_system(
        system, "vision_observe", {"source_kind": "camera", "idempotency_key": ""}
    )
    assert result.status_code == 400
    assert (
        cast(dict[str, object], result.payload["error"])["code"]
        == "INPUT_IDEMPOTENCY_KEY"
    )
