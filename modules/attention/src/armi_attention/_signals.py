"""Exact signal receipt and consumption within the existing opportunity fact."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from uuid import UUID

from armi_kernel.application import ConsiderationSignal
from armi_runtime_foundation import PostgreSQLTransaction


def signal_metadata(
    signals: tuple[ConsiderationSignal, ...], *, frozen_at: datetime | None
) -> str:
    return json.dumps(
        {
            "schema_kind": "armi.consideration-signals",
            "frozen_at": None if frozen_at is None else frozen_at.isoformat(),
            "signals": [
                {
                    "owner": signal.owner,
                    "object_ref": str(signal.object_ref),
                    "condition_version": signal.condition_version,
                    "reason": signal.reason,
                    "eligible_at": signal.eligible_at.isoformat(),
                }
                for signal in signals
            ],
        }
    )


async def unconsumed_signals(
    transaction: PostgreSQLTransaction,
    *,
    subject_id: UUID,
    signals: tuple[ConsiderationSignal, ...],
) -> tuple[ConsiderationSignal, ...]:
    if not signals:
        return ()
    rows = await (
        await transaction.execute(
            """SELECT entry->>'owner',entry->>'object_ref',entry->>'condition_version'
           FROM armi.opportunities o,
             LATERAL jsonb_array_elements(o.consideration_signals->'signals') entry
           WHERE o.subject_id=%s
             AND o.consideration_signals->>'frozen_at' IS NOT NULL
             AND entry->>'object_ref'=ANY(%s::text[])""",
            (subject_id, list({str(signal.object_ref) for signal in signals})),
        )
    ).fetchall()
    consumed = {tuple(row) for row in rows}
    return tuple(signal for signal in signals if signal.identity not in consumed)


async def freeze_signals(
    transaction: PostgreSQLTransaction,
    *,
    opportunity_id: UUID,
    signals: tuple[ConsiderationSignal, ...],
    frozen_at: datetime,
) -> None:
    from .api import LifeViolation

    if any(signal.eligible_at > frozen_at for signal in signals):
        raise LifeViolation("LIFE-SIGNAL-NOT-DUE")
    result = await transaction.execute(
        """UPDATE armi.opportunities SET consideration_signals=%s::jsonb
           WHERE opportunity_id=%s AND current_disposition='selected'
             AND (consideration_signals IS NULL OR consideration_signals->>'frozen_at' IS NULL)""",
        (signal_metadata(signals, frozen_at=frozen_at), opportunity_id),
    )
    if result.rowcount != 1:
        raise LifeViolation("LIFE-SIGNAL-FREEZE-STALE")


def project_signal_status(
    result: dict[str, object],
    signals: tuple[ConsiderationSignal, ...],
    consumed: frozenset[tuple[str, str, str]],
) -> None:
    pending = tuple(signal for signal in signals if signal.identity not in consumed)
    result["consideration_signals"] = json.loads(
        signal_metadata(pending, frozen_at=None)
    )["signals"]
    if result.get("next_consideration_at") is None:
        return
    base = datetime.fromisoformat(str(result["next_consideration_at"]))
    effective = min((signal.eligible_at for signal in pending), default=base)
    effective = min(base, effective)
    if result.get("last_check_started_at") is not None:
        effective = max(
            effective,
            datetime.fromisoformat(str(result["last_check_started_at"]))
            + timedelta(seconds=60),
        )
    result["effective_consideration_at"] = effective.isoformat()
    if result["state"] in {"scheduled", "ready"}:
        as_of = datetime.fromisoformat(str(result["observed_at"]))
        result["state"] = "ready" if effective <= as_of else "scheduled"
