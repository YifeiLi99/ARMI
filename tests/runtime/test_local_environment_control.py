from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid7

import pytest
from armi_local_control import ConfigurationViolation, RuntimeViolation
from armi_local_control.lifecycle import (
    LocalEnvironmentController,
    PostgreSQLControlBinding,
    environment_control_lock,
)


def controller(root: Path) -> LocalEnvironmentController:
    return LocalEnvironmentController(
        environment_root=root,
        environment_id=str(uuid7()),
        incarnation=1,
        defaults_path=root / "defaults.yaml",
    )


def test_start_waits_for_readiness_after_dependencies(tmp_path: Path) -> None:
    control = controller(tmp_path)
    calls = []
    runtime = Mock()
    runtime.start.side_effect = lambda: calls.append("runtime") or {"status": "started"}
    runtime.status.side_effect = [
        {"status": "running", "runtime": {"readiness": "starting"}},
        {"status": "running", "runtime": {"readiness": "ready"}},
    ]
    control.runtime = runtime
    semantic = Mock()
    semantic.start.side_effect = lambda: calls.append("semantic") or {"status": "ready"}
    with (
        patch.object(
            control, "database", side_effect=lambda _: calls.append("database") or {}
        ),
        patch.object(control, "_semantic", return_value=semantic),
        patch("armi_local_control.lifecycle.time.sleep"),
    ):
        result = control.execute("start")
    assert calls == ["database", "semantic", "runtime"]
    assert runtime.status.call_count == 2
    assert result["status"] == "ready"


def test_shared_postgresql_is_never_stopped(tmp_path: Path) -> None:
    control = controller(tmp_path)
    control.postgresql = PostgreSQLControlBinding(
        ownership="shared",
        installation_root=tmp_path / "pgsql",
        data_directory=tmp_path / "postgresql/data",
        port=15432,
    )
    with patch("armi_local_control.lifecycle.NativePostgreSQL") as run:
        assert control.database("stop")["action"] == "not_managed"
    run.assert_not_called()


def test_external_database_status_uses_bound_probe_without_process_control(tmp_path):
    control = controller(tmp_path)
    probe = Mock(return_value={"reachability": "reachable", "role_status": "verified"})
    control.database_probe = probe
    with patch("armi_local_control.lifecycle.NativePostgreSQL") as run:
        assert control.database("status")["reachability"] == "reachable"
        assert control.database("stop")["action"] == "not_managed"
    probe.assert_called_once()
    run.assert_not_called()


def test_database_timeout_is_unknown_and_does_not_start_runtime(tmp_path: Path) -> None:
    control = controller(tmp_path)
    control.postgresql = PostgreSQLControlBinding(
        ownership="exclusive",
        installation_root=tmp_path / "pgsql",
        data_directory=tmp_path / "postgresql/data",
        port=15432,
    )
    control.runtime = Mock()
    with (
        patch(
            "armi_local_control.lifecycle.NativePostgreSQL",
            side_effect=RuntimeViolation("LOCAL-POSTGRESQL-UNKNOWN", "start timed out"),
        ) as run,
        pytest.raises(RuntimeViolation) as failure,
    ):
        control.execute("start")
    assert failure.value.code == "LOCAL-POSTGRESQL-UNKNOWN"
    assert run.call_count == 1
    control.runtime.start.assert_not_called()


def test_failed_runtime_drain_preserves_dependencies(tmp_path: Path) -> None:
    control = controller(tmp_path)
    control.runtime = Mock()
    control.runtime.stop.side_effect = RuntimeViolation(
        "CLI-RUNTIME-STOP", "drain failed"
    )
    with (
        patch.object(control, "database") as database,
        patch("armi_local_control.lifecycle.SemanticRecallProcessManager") as semantic,
        pytest.raises(RuntimeViolation),
    ):
        control.execute("stop")
    database.assert_not_called()
    semantic.assert_not_called()


def test_unconfirmed_runtime_stop_preserves_dependencies(tmp_path: Path) -> None:
    control = controller(tmp_path)
    control.runtime = Mock()
    control.runtime.stop.return_value = {"status": "draining"}
    with (
        patch.object(control, "database") as database,
        patch("armi_local_control.lifecycle.SemanticRecallProcessManager") as semantic,
        pytest.raises(RuntimeViolation, match="LOCAL-RUNTIME-STOP-UNKNOWN"),
    ):
        control.execute("stop")
    database.assert_not_called()
    semantic.assert_not_called()


def test_lifecycle_cannot_overlap_maintenance_lock(tmp_path: Path) -> None:
    control = controller(tmp_path)
    control.runtime = Mock()
    with (
        environment_control_lock(tmp_path, control.environment_id),
        patch.object(control, "database") as database,
        pytest.raises(RuntimeViolation, match="CLI-RUNTIME-CONTROL-BUSY"),
    ):
        control.execute("start")
    database.assert_not_called()
    control.runtime.start.assert_not_called()


def test_status_preserves_evidence_when_configuration_is_invalid(
    tmp_path: Path,
) -> None:
    control = controller(tmp_path)
    control.runtime = Mock()
    control.runtime.status.return_value = {"status": "stopped"}
    with patch.object(
        control,
        "_semantic",
        side_effect=ConfigurationViolation("CFG-TYPE", "invalid configuration"),
    ):
        result = control.execute("status")
    assert result["runtime"]["status"] == "stopped"
    assert result["postgresql"]["ownership"] == "external"
    assert result["semantic_recall"]["error_code"] == "CFG-TYPE"


def test_postgresql_status_verifies_database_after_native_process(
    tmp_path: Path,
) -> None:
    control = controller(tmp_path)
    control.postgresql = PostgreSQLControlBinding(
        ownership="exclusive",
        installation_root=tmp_path / "pgsql",
        data_directory=tmp_path / "postgresql/data",
        port=15432,
    )
    probe = Mock(return_value={"role_status": "verified"})
    control.database_probe = probe
    with patch("armi_local_control.lifecycle.NativePostgreSQL") as native:
        native.return_value.execute.return_value = {
            "ownership": "exclusive",
            "status": "ready",
            "port": 15432,
        }
        result = control.database("status")
    native.return_value.execute.assert_called_once_with("status")
    probe.assert_called_once()
    assert result["role_status"] == "verified"
