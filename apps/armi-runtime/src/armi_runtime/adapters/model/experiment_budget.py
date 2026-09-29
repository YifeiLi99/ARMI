"""Fail-closed dispatch reservations, only bound in a validated simulation environment."""

from __future__ import annotations

import json
import os
from decimal import Decimal
from pathlib import Path
from typing import Any

from armi_kernel.application import ModelViolation, ProviderCallReceipt


class ExperimentBudget:
    """Persist reservations before dispatch; never hide or replace provider receipts."""

    @classmethod
    def load(cls, root: Path) -> ExperimentBudget | None:
        path = root / "provider-budget.json"
        return cls(path) if path.exists() else None

    def __init__(self, path: Path) -> None:
        self.path = path
        state = json.loads(path.read_text(encoding="utf-8"))
        if state.get("schema_kind") != "armi.simulation-budget" or any(
            call["pending"] for call in state["calls"].values()
        ):
            # Unsettled requests must be reviewed, never silently resumed.
            raise ModelViolation("MODEL-EXPERIMENT-BUDGET-STATE")
        self.state: dict[str, Any] = state

    def _save(self) -> None:
        temporary = self.path.with_suffix(".pending")
        temporary.write_text(json.dumps(self.state, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, self.path)

    def __call__(self, receipt: ProviderCallReceipt) -> None:
        if not receipt.billable and receipt.call_id not in self.state["calls"]:
            return
        calls = self.state["calls"]
        if receipt.registration:
            if self.state.get("stopped"):
                raise ModelViolation("MODEL-EXPERIMENT-BUDGET-STOPPED")
            # Both reservations exceed the configured request maximum at the
            # verified price. Other providers/models need a separate experiment.
            if receipt.provider == "typesafe" and receipt.model == "jev-1.13.0":
                currency, reserve = "USD", Decimal("0.005")
            elif receipt.provider == "qwen" and receipt.model == "qwen3.8-flash":
                currency, reserve = "CNY", Decimal("1")
            else:
                self.state["stopped"] = "unpriced_provider"
                self._save()
                raise ModelViolation("MODEL-EXPERIMENT-BUDGET-PRICE")
            used = sum(
                (
                    Decimal(call["amount"])
                    for call in calls.values()
                    if call["currency"] == currency
                ),
                Decimal(0),
            )
            if len(calls) >= self.state["max_calls"] or used + reserve > Decimal(
                self.state["limits"][currency]
            ):
                self.state["stopped"] = "reservation_limit"
                self._save()
                raise ModelViolation("MODEL-EXPERIMENT-BUDGET-LIMIT")
            calls[receipt.call_id] = {
                "currency": currency,
                "amount": str(reserve),
                "pending": True,
            }
        elif receipt.finished_at is not None:
            call = calls[receipt.call_id]
            quantities = {q.unit.value: q.quantity for q in receipt.quantities}
            if receipt.cost.status == "not_billable":
                amount = Decimal(0)
            elif receipt.outcome != "returned":
                self.state["stopped"] = "unknown_cost_or_outcome"
                self._save()
                return
            elif call["currency"] == "USD" and "input_tokens" in quantities:
                amount = (
                    Decimal(quantities["input_tokens"]) * Decimal("0.042") / 1_000_000
                )
            elif (
                receipt.cost.status == "estimated"
                and receipt.cost.known_microyuan is not None
            ):
                amount = Decimal(receipt.cost.known_microyuan) / 1_000_000
            else:
                self.state["stopped"] = "unknown_cost_or_outcome"
                self._save()
                return
            call.update(amount=str(amount), pending=False)
        self._save()
