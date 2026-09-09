"""Read the capability catalog with the current Runtime's availability."""

from collections.abc import Callable
from uuid import UUID

import rfc8785
from armi_runtime_foundation import PostgreSQLTransaction

from .api import CapabilityAvailability, CapabilityContextStatePayload


class PostgreSQLCapabilityCatalog:
    def __init__(self, availability: Callable[[], CapabilityAvailability]) -> None:
        self._availability = availability

    async def context_state_payloads(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
    ) -> tuple[CapabilityContextStatePayload, ...]:
        del subject_id
        rows = await (
            await transaction.execute(
                """SELECT capability_id, capability_kind, operation_class, configuration_version
               FROM armi.capabilities WHERE capability_kind='codex.delegated-work'
               ORDER BY capability_kind"""
            )
        ).fetchall()
        state = self._availability()
        status = "available" if state.available else "unavailable"
        return tuple(
            (
                row[0],
                int(row[3]),
                rfc8785.dumps(
                    {
                        "schema_version": "armi.capability-state.v2",
                        "capability_ref": str(row[0]),
                        "capability_kind": str(row[1]),
                        "operation": str(row[2]),
                        "enabled": state.enabled,
                        "availability_status": status,
                        "reason_code": state.reason_code,
                    }
                ),
                status,
            )
            for row in rows
        )
