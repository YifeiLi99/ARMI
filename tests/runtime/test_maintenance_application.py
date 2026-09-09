"""Operational use cases retain their safety checks behind the shared wire."""

import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid7

import pytest
from armi_local_control import RuntimeViolation
from armi_local_control.maintenance import MaintenanceInvocation
from armi_runtime.composition.environment import prepare_environment
from armi_runtime.composition.maintenance import execute_maintenance
from armi_runtime.composition.napcat_process import NapCatWebUIOpenResult


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch) -> None:
    # The quality runner's toolchain variables are not Runtime deployment
    # configuration. These use cases run against only the test's explicit root.
    for name in tuple(os.environ):
        if name.startswith("ARMI_"):
            monkeypatch.delenv(name)


def request(root: Path, action: str, **arguments) -> MaintenanceInvocation:
    environment_id = uuid7()
    (root / "data").mkdir()
    (root / "secrets").mkdir()
    (root / "environment.yaml").write_text(
        json.dumps(
            {
                "creator": {"port": 43123},
                "environment": {
                    "environment_id": str(environment_id),
                    "data_root": str(root / "data"),
                },
            }
        ),
        encoding="utf-8",
    )
    return MaintenanceInvocation.model_validate(
        {
            "environment_id": environment_id,
            "environment_root": root,
            "action": action,
            **arguments,
        }
    )


def test_calibration_refuses_live_runtime_before_starting_model(tmp_path: Path) -> None:
    invocation = request(tmp_path, "semantic_calibrate")
    with (
        patch(
            "armi_runtime.composition.maintenance.RuntimeProcessManager.status",
            return_value={"status": "running"},
        ),
        patch(
            "armi_runtime.composition.maintenance.SemanticRecallProcessManager.calibrate"
        ) as calibrate,
        pytest.raises(RuntimeViolation) as failure,
    ):
        execute_maintenance(invocation)
    assert failure.value.code == "SEMANTIC-RECALL-CALIBRATION-BUSY"
    calibrate.assert_not_called()


@pytest.mark.parametrize(
    "action,handler,scope",
    [
        (
            "database_install",
            "install_operator_schema",
            {"database.migrator": "database.migrator"},
        ),
        (
            "database_check",
            "inspect_operator_schema",
            {"database.status": "database.runtime"},
        ),
        ("birth", "execute_birth", {"database.birth": "database.runtime"}),
        (
            "database_maintain",
            "run_database_maintenance",
            {"database.maintenance": "database.migrator"},
        ),
        ("capacity_check", "run_runtime_capacity_baseline", {}),
    ],
)
def test_maintenance_uses_exact_scope_and_preserves_result(
    tmp_path, action, handler, scope
):
    invocation = request(tmp_path, action, apply=action == "database_maintain")
    result = {"status": "attention", "issue_codes": ["TEST-EVIDENCE"]}
    with (
        patch(
            "armi_runtime.composition.maintenance.prepare_environment",
            wraps=prepare_environment,
        ) as prepare,
        patch(
            "armi_runtime.composition.maintenance." + handler,
            return_value=SimpleNamespace(safe_view=lambda: result),
        ) as operation,
    ):
        assert execute_maintenance(invocation) == result
    assert prepare.call_args.kwargs["credential_scope"] == scope
    operation.assert_called_once()


def test_database_maintenance_requires_explicit_apply(tmp_path):
    invocation = request(tmp_path, "database_maintain")
    with (
        patch(
            "armi_runtime.composition.maintenance.run_database_maintenance"
        ) as operation,
        pytest.raises(RuntimeViolation) as error,
    ):
        execute_maintenance(invocation)
    assert error.value.code == "ADMIN-MAINTENANCE-APPLY-REQUIRED"
    operation.assert_not_called()


def test_artifact_cleanup_defaults_to_read_only(tmp_path):
    invocation = request(tmp_path, "artifact_cleanup")
    with (
        patch(
            "armi_runtime.composition.maintenance.run_artifact_retention",
            return_value=SimpleNamespace(safe_view=lambda: {"status": "dry_run"}),
        ) as cleanup,
        patch(
            "armi_runtime.composition.maintenance.prepare_environment",
            wraps=prepare_environment,
        ) as prepare,
    ):
        assert execute_maintenance(invocation) == {"status": "dry_run"}
    assert prepare.call_args.kwargs["credential_scope"] == {
        "database.artifact-maintenance": "database.runtime"
    }
    cleanup.assert_awaited_once()
    assert cleanup.await_args is not None
    assert cleanup.await_args.kwargs["apply"] is False


def test_semantic_status_keeps_storage_and_process_evidence(tmp_path: Path) -> None:
    invocation = request(tmp_path, "semantic_status")
    with (
        patch(
            "armi_runtime.composition.maintenance.SemanticRecallProcessManager.status",
            return_value={"status": "stopped"},
        ),
        patch(
            "armi_runtime.composition.maintenance.inspect_semantic_recall_storage",
            return_value={"database_status": "current", "projected_chunks": 12},
        ),
    ):
        result = execute_maintenance(invocation)
    assert result == {
        "status": "stopped",
        "database_status": "current",
        "projected_chunks": 12,
    }


def test_napcat_browser_convenience_preserves_explicit_token_delivery(
    tmp_path: Path,
) -> None:
    invocation = request(tmp_path, "napcat_open", auto_login=True)
    with patch(
        "armi_runtime.composition.maintenance.NapCatProcessManager.open_webui",
        return_value=NapCatWebUIOpenResult("http://127.0.0.1:1234", "url_query"),
    ) as opened:
        result = execute_maintenance(invocation)
    opened.assert_called_once_with(auto_login=True)
    assert result == {
        "status": "opened",
        "webui_url": "http://127.0.0.1:1234",
        "token_delivery": "url_query",
    }


def test_maintenance_rejects_parameters_for_another_action(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="ADMIN-MAINTENANCE-ARGUMENTS"):
        request(tmp_path, "semantic_status", approved_official_direct=True)
