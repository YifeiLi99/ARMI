"""Operational use cases retain their safety checks behind the shared wire."""

import json
from pathlib import Path
from unittest.mock import patch
from uuid import uuid7

import pytest
from armi_local_control import RuntimeViolation
from armi_local_control.maintenance import MaintenanceInvocation
from armi_runtime.composition.maintenance import execute_maintenance
from armi_runtime.composition.napcat_process import NapCatWebUIOpenResult


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
