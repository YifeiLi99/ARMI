from pathlib import Path

import pytest
from armi_admin.application.invocations import (
    InvocationJournal,
    invocation_completed_step,
    invocation_progress,
)


def test_active_call_reports_progress_then_preserves_interrupted_phase(
    tmp_path: Path,
) -> None:
    journal = InvocationJournal(tmp_path, "binding")

    def execute():
        invocation_progress("runtime.readiness")
        progress = InvocationJournal(tmp_path, "binding").read("start", "stable")
        assert progress["state"] == "running"
        assert progress["phase"] == "runtime.readiness"
        raise RuntimeError("interrupted")

    with pytest.raises(RuntimeError, match="interrupted"):
        journal.invoke(
            name="start", key="stable", request_digest="request", execute=execute
        )
    receipt = journal.read("start", "stable")
    assert receipt["state"] == "unknown"
    assert receipt["phase"] == "runtime.readiness"


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


def test_reconcile_recovers_lost_receipt_without_reexecuting(
    tmp_path: Path, monkeypatch
) -> None:
    journal = InvocationJournal(tmp_path, "binding")
    save = journal.save_record
    outcome = {"status": "succeeded", "operation_id": "original-result"}

    def interrupted_save(path, record):
        if record.get("state") == "finished":
            raise OSError("lost final receipt")
        save(path, record)

    monkeypatch.setattr(journal, "save_record", interrupted_save)
    with pytest.raises(OSError, match="lost final receipt"):
        journal.invoke(
            name="start",
            key="key",
            request_digest="digest",
            audit={"scope": "environment_start"},
            execute=lambda: outcome,
        )
    recovered = InvocationJournal(tmp_path, "binding")
    assert recovered.read("start", "key")["state"] == "unknown"
    result = recovered.reconcile(
        "start",
        "key",
        authorized_scopes=("environment_start",),
        observe=lambda _: pytest.fail("recorded outcome needs no external observation"),
    )
    assert result["state"] == "finished"
    assert result["result"] == outcome
    assert (
        recovered.invoke(
            name="start",
            key="key",
            request_digest="digest",
            execute=lambda: pytest.fail("must not reexecute"),
        )
        == outcome
    )


def test_reconcile_rechecks_original_permission_and_preserves_unknown(
    tmp_path: Path,
) -> None:
    journal = InvocationJournal(tmp_path, "binding")
    with pytest.raises(RuntimeError):
        journal.invoke(
            name="repair",
            key="key",
            request_digest="digest",
            audit={"scope": "apply_correction"},
            execute=lambda: (_ for _ in ()).throw(RuntimeError("interrupted")),
        )
    with pytest.raises(ValueError, match="ADMIN-SCOPE-REQUIRED"):
        journal.reconcile(
            "repair",
            "key",
            authorized_scopes=(),
            observe=lambda _: pytest.fail("unauthorized observation"),
        )
    result = journal.reconcile(
        "repair",
        "key",
        authorized_scopes=("apply_correction",),
        observe=lambda _: (None, {"basis": "insufficient_evidence"}),
    )
    assert result["state"] == "unknown"
    assert result["reconciliation"]["basis"] == "insufficient_evidence"


def test_completed_phase_survives_interruption_without_completing_the_call(
    tmp_path: Path,
) -> None:
    journal = InvocationJournal(tmp_path, "binding")

    def interrupted():
        invocation_progress("runtime.start")
        invocation_completed_step("runtime.start", {"status": "started", "pid": 123})
        invocation_progress("runtime.readiness")
        raise RuntimeError("interrupted before readiness")

    with pytest.raises(RuntimeError, match="before readiness"):
        journal.invoke(
            name="environment_start",
            key="start",
            request_digest="digest",
            audit={"scope": "environment_start"},
            execute=interrupted,
        )

    def observe(evidence):
        assert evidence.completed_steps == {
            "runtime.start": {"status": "started", "pid": 123}
        }
        return None, {"basis": "insufficient_evidence"}

    result = InvocationJournal(tmp_path, "binding").reconcile(
        "environment_start",
        "start",
        authorized_scopes=("environment_start",),
        observe=observe,
    )
    assert result["state"] == "unknown"
    assert result["phase"] == "runtime.readiness"
