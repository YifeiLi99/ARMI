"""Runtime availability, without approval or permission state."""

import json

import pytest
from armi_capability.api import CapabilityAvailability
from armi_capability.bootstrap import bootstrap_capability


@pytest.mark.parametrize(
    "kind",
    ["codex.delegated-work", "vision.camera", "vision.screen", "life.query"],
)
@pytest.mark.parametrize(
    "availability",
    [
        CapabilityAvailability(False, False, "CODEX-DISABLED"),
        CapabilityAvailability(True, False, "CODEX-CREDENTIAL-MISSING"),
        CapabilityAvailability(True, True, None),
    ],
)
def test_catalog_uses_runtime_availability(
    availability: CapabilityAvailability,
    kind: str,
) -> None:
    catalog = bootstrap_capability(lambda: {kind: availability})
    rows = catalog.context_state_payloads()
    if not availability.enabled:
        assert rows == ()
        return
    payload = json.loads(rows[0][2])
    assert payload["capability_kind"] == kind
    assert payload["enabled"] is availability.enabled
    assert payload["availability_status"] == (
        "available" if availability.available else "unavailable"
    )
    assert payload["reason_code"] == availability.reason_code
    assert "grants" not in payload
