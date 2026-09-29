"""Simulation spending caps apply before dispatch, including format retries."""

import json
from dataclasses import replace

import pytest
from armi_kernel.application import (
    ModelViolation,
    PriceCatalog,
    ProviderMeterScope,
    provider_call,
    provider_meter_scope,
)
from armi_runtime.adapters.model.experiment_budget import ExperimentBudget


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["known", "unknown", "limit"])
async def test_budget_stops_before_another_billable_dispatch(tmp_path, outcome):
    path = tmp_path / "provider-budget.json"
    path.write_text(
        json.dumps(
            {
                "schema_kind": "armi.simulation-budget",
                "max_calls": 1 if outcome == "limit" else 300,
                "limits": {"USD": "0.5", "CNY": "10"},
                "calls": {},
            }
        )
    )
    guard = ExperimentBudget(path)
    receipts = []

    async def write(receipt):
        guard(receipt)
        receipts.append(receipt)

    with provider_meter_scope(ProviderMeterScope(write, PriceCatalog(()), "test")):
        async with provider_call(
            provider="typesafe", model="jev-1.13.0", service="generation"
        ) as call:
            if outcome != "unknown":
                await call.capture(
                    usage={"input_tokens": 1000, "output_tokens": 0},
                    response_model="jev-1.13.0",
                )
        if outcome in {"unknown", "limit"}:
            with pytest.raises(ModelViolation, match="MODEL-EXPERIMENT-BUDGET"):
                async with provider_call(
                    provider="typesafe", model="jev-1.13.0", service="generation"
                ):
                    pytest.fail("must not dispatch")
        else:
            state = json.loads(path.read_text())
            assert state["calls"][receipts[0].call_id]["amount"] == "0.000042"
            # A never-sent attempt releases its reservation without charging.
            guard(
                replace(
                    receipts[-1],
                    billable=False,
                    cost=replace(receipts[-1].cost, status="not_billable"),
                )
            )
            assert (
                json.loads(path.read_text())["calls"][receipts[0].call_id]["amount"]
                == "0"
            )
