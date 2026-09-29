"""Compose owner clock reads; no owner table is read through another repository."""

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
