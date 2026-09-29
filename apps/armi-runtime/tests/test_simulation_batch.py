"""Batching transport never jumps over a model or any earlier business deadline."""

from unittest.mock import AsyncMock, Mock

import pytest
from armi_runtime.composition.simulation import advance_idle_batch


@pytest.mark.asyncio
@pytest.mark.parametrize("stop", ["busy", "deadline"])
async def test_batch_preserves_each_original_poll_and_stops(stop):
    events = []

    async def maintain():
        events.append("maintain")

    async def admit():
        events.append("admit")

    advance = AsyncMock(
        side_effect=[
            {
                "status": "advanced",
                "advanced_seconds": 5,
                "offset_microseconds": 5_000_000,
            },
            {
                "status": "busy" if stop == "busy" else "advanced",
                "advanced_seconds": 0 if stop == "busy" else 2,
                "offset_microseconds": 5_000_000 if stop == "busy" else 7_000_000,
            },
        ]
    )
    offset = Mock()
    result = await advance_idle_batch(
        3600, maintain=maintain, admit=admit, advance=advance, set_offset=offset
    )
    assert events == ["maintain", "admit"] * 2
    assert result["advanced_seconds"] == (5 if stop == "busy" else 7)
    assert advance.await_count == 2
    assert offset.call_count == (1 if stop == "busy" else 2)
