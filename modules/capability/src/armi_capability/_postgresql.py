"""Read the capability catalog with the current Runtime's availability."""

from collections.abc import Callable, Mapping
from uuid import UUID

import rfc8785
from armi_runtime_foundation import PostgreSQLTransaction

from .api import CapabilityAvailability, CapabilityContextStatePayload


class PostgreSQLCapabilityCatalog:
    def __init__(
        self, availability: Callable[[], Mapping[str, CapabilityAvailability]]
    ) -> None:
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
        states = self._availability()
        # Stable identities for configuration-owned built-in entries; they are
        # Context sources, not grants or writable permission records.
        rows = [
            *rows,
            *(
                (UUID(identity), kind, operation, 1)
                for identity, kind, operation in (
                    (
                        "01985d00-0000-7000-8000-000000000035",
                        "vision.camera",
                        "observe_camera",
                    ),
                    (
                        "01985d00-0000-7000-8000-000000000036",
                        "vision.screen",
                        "observe_screen",
                    ),
                    (
                        "01985d00-0000-7000-8000-000000000037",
                        "life.query",
                        "read_life_records",
                    ),
                )
            ),
        ]
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
            if (state := states.get(str(row[1]))) is not None and state.enabled
            for status in ("available" if state.available else "unavailable",)
        )
