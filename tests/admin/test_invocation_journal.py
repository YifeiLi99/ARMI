from pathlib import Path

import pytest
from armi_admin.application.invocations import InvocationJournal


def test_receipt_survives_new_process_instance_and_conflicts(tmp_path: Path) -> None:
    calls = []

    def execute():
        calls.append(True)
        return {"status": "succeeded", "operation_id": "same-result"}

    first = InvocationJournal(tmp_path, "binding").invoke(
        name="repair", key="stable", request_digest="request", execute=execute
    )
    second = InvocationJournal(tmp_path, "binding").invoke(
        name="repair", key="stable", request_digest="request", execute=execute
    )
    assert first == second
    assert calls == [True]
    receipt = InvocationJournal(tmp_path, "binding").read("repair", "stable")
    assert receipt["state"] == "finished"
    assert receipt["result"] == first
    with pytest.raises(ValueError, match="ADMIN-IDEMPOTENCY-CONFLICT"):
        InvocationJournal(tmp_path, "binding").invoke(
            name="repair", key="stable", request_digest="different", execute=execute
        )


def test_interrupted_invocation_never_replays_side_effect(tmp_path: Path) -> None:
    def interrupted():
        raise RuntimeError("process interrupted after dispatch")

    with pytest.raises(RuntimeError):
        InvocationJournal(tmp_path, "binding").invoke(
            name="repair", key="stable", request_digest="request", execute=interrupted
        )
    with pytest.raises(ValueError, match="ADMIN-INVOCATION-UNKNOWN"):
        InvocationJournal(tmp_path, "binding").invoke(
            name="repair",
            key="stable",
            request_digest="request",
            execute=lambda: pytest.fail("must not replay"),
        )
    assert (
        InvocationJournal(tmp_path, "binding").read("repair", "stable")["state"]
        == "unknown"
    )
