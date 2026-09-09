"""Runtime availability, without approval or permission state."""

import json
from typing import Any, cast
from uuid import uuid7

import pytest
from armi_capability.api import CapabilityAvailability
from armi_capability.bootstrap import bootstrap_capability


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "availability",
    [
        CapabilityAvailability(False, False, "CODEX-DISABLED"),
        CapabilityAvailability(True, False, "CODEX-CREDENTIAL-MISSING"),
        CapabilityAvailability(True, True, None),
    ],
)
async def test_catalog_uses_runtime_availability(
    availability: CapabilityAvailability,
) -> None:
    class Transaction:
        async def execute(self, *_args: object) -> Any:
            return self

        async def fetchall(self) -> list[tuple[object, ...]]:
            return [(uuid7(), "codex.delegated-work", "execute", 1)]

    catalog = bootstrap_capability(lambda: availability)
    rows = await catalog.context_state_payloads(
        cast(Any, Transaction()), subject_id=uuid7()
    )
    payload = json.loads(rows[0][2])
    assert payload["enabled"] is availability.enabled
    assert payload["availability_status"] == (
        "available" if availability.available else "unavailable"
    )
    assert payload["reason_code"] == availability.reason_code
    assert "grants" not in payload
