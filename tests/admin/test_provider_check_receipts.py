import json
from dataclasses import replace
from typing import Any, cast
from uuid import uuid7

import pytest
from armi_kernel.application import (
    PriceCatalog,
    ProviderMeterScope,
    provider_call,
    provider_meter_scope,
)
from armi_local_control import ProviderCheckReceipts
from armi_local_control.process_identity import (
    ManagedProcessIdentity,
    ManagedProcessState,
)


@pytest.mark.asyncio
async def test_probe_receipts_survive_owner_restart_and_keep_partial_usage(
    tmp_path, monkeypatch
):
    store = ProviderCheckReceipts(tmp_path)
    verification = str(uuid7())

    async def save(call):
        store.save(
            verification_id=verification,
            credential_name="model.ark_api_key",
            call=call.document(),
        )

    with provider_meter_scope(
        ProviderMeterScope(save, PriceCatalog(()), "credential_verification")
    ):
        async with provider_call(
            provider="test", model="test", service="generation"
        ) as call:
            await call.capture(
                usage={"output_tokens": 7}, provider_request_id="response-1"
            )
            pending = call.receipt
    # Simulate death after the partial receipt was durable, without a final callback.
    await save(replace(pending, outcome="pending"))
    monkeypatch.setattr(
        ManagedProcessIdentity, "inspect", lambda self: ManagedProcessState.ABSENT
    )
    restarted = ProviderCheckReceipts(tmp_path)
    row = cast(dict[str, Any], restarted.read()[0]["call"])
    assert row["outcome"] == "unknown"
    assert row["provider_request_id"] == "response-1"
    assert row["quantities"][0]["quantity"] == 7
    assert row["cost"]["known_microyuan"] is None
    restarted.settle_interrupted(verification)
    raw = json.loads(
        next(
            (tmp_path / "run/admin-invocations/provider-calls").glob("*.json")
        ).read_bytes()
    )
    assert raw["call"]["outcome"] == "unknown"
    assert raw["call"]["finished_at"] is not None
    restarted.settle_interrupted(verification)
    assert len(restarted.read()) == 1


@pytest.mark.asyncio
async def test_probe_registration_storage_failure_prevents_request(
    tmp_path, monkeypatch
):
    store = ProviderCheckReceipts(tmp_path)
    verification = str(uuid7())
    dispatched = []

    def fail(*args, **kwargs):
        raise OSError("disk unavailable")

    monkeypatch.setattr("armi_local_control.provider_check_receipts.os.replace", fail)

    async def save(call):
        store.save(
            verification_id=verification,
            credential_name="speech.volc_credentials",
            call=call.document(),
        )

    with (
        provider_meter_scope(
            ProviderMeterScope(save, PriceCatalog(()), "credential_verification")
        ),
        pytest.raises(OSError),
    ):
        async with provider_call(provider="test", model="asr-resource", service="asr"):
            dispatched.append(True)
    assert dispatched == []
    assert store.read() == ()
