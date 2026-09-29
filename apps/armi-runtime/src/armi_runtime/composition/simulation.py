"""Compose owner clock reads; no owner table is read through another repository."""

from collections.abc import Awaitable, Callable
from typing import Any

from armi_activity.bootstrap import bootstrap_simulation_read as activity_clock
from armi_attention.bootstrap import bootstrap_simulation_read as attention_clock
from armi_cognition.bootstrap import bootstrap_simulation_read as cognition_clock
from armi_effect.bootstrap import bootstrap_simulation_read as effect_clock
from armi_runtime_foundation import PostgreSQLTransaction, SimulationState
from armi_sleep.bootstrap import bootstrap_simulation_read as sleep_clock


async def read_simulation_state(transaction: PostgreSQLTransaction) -> SimulationState:
    states = [
        await port.read(transaction)
        for port in (
            activity_clock(),
            attention_clock(),
            cognition_clock(),
            effect_clock(),
            sleep_clock(),
        )
    ]
    deadlines = [state.next_at for state in states if state.next_at is not None]
    return SimulationState(
        any(state.busy for state in states), min(deadlines, default=None)
    )


async def advance_idle_batch(
    seconds: int,
    *,
    maintain: Callable[[], Awaitable[Any]],
    admit: Callable[[], Awaitable[Any]],
    advance: Callable[[int], Awaitable[dict[str, Any]]],
    set_offset: Callable[[int], None],
) -> dict[str, Any]:
    """Amortize transport only; visit every original poll and stop at due work."""
    total = 0.0
    result: dict[str, Any] = {}
    for _ in range(120):
        remaining = int(seconds - total)
        if remaining < 1:
            break
        await maintain()
        await admit()
        result = await advance(remaining)
        delta = result["advanced_seconds"]
        if result["status"] != "advanced":
            break
        set_offset(result["offset_microseconds"])
        total += delta
        if delta < 5:
            break
    return {
        **result,
        "status": "advanced" if total else result.get("status", "busy"),
        "advanced_seconds": total,
    }
