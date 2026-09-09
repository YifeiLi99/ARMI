import subprocess
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid7

import pytest
from armi_local_control import ConfigurationViolation, RuntimeViolation
from armi_local_control.lifecycle import (
    LocalEnvironmentController,
    PostgreSQLControlBinding,
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
        compose_file=tmp_path / "compose.yaml",
        environment_file=tmp_path / "postgres.env",
        project_name="shared",
        service_name="postgresql",
    )
    with patch("armi_local_control.lifecycle.subprocess.run") as run:
        assert control.database("stop")["action"] == "not_managed"
    run.assert_not_called()


def test_database_timeout_is_unknown_and_does_not_start_runtime(tmp_path: Path) -> None:
    control = controller(tmp_path)
    control.postgresql = PostgreSQLControlBinding(
        ownership="exclusive",
        compose_file=tmp_path / "compose.yaml",
        environment_file=tmp_path / "postgres.env",
        project_name="armi",
        service_name="postgresql",
    )
    control.runtime = Mock()
    with (
        patch(
            "armi_local_control.lifecycle.subprocess.run",
            side_effect=subprocess.TimeoutExpired("docker", 120),
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


@pytest.mark.parametrize(
    "payload",
    [
        b'{"State":"running","Health":"healthy"}\n',
        b'[{"State":"running","Health":"healthy"}]',
    ],
)
def test_postgresql_status_accepts_compose_json_forms(
    tmp_path: Path, payload: bytes
) -> None:
    control = controller(tmp_path)
    control.postgresql = PostgreSQLControlBinding(
        ownership="exclusive",
        compose_file=tmp_path / "compose.yaml",
        environment_file=tmp_path / "postgres.env",
        project_name="armi",
        service_name="postgresql",
    )
    with patch(
        "armi_local_control.lifecycle.subprocess.run",
        return_value=Mock(returncode=0, stdout=payload),
    ):
        assert control.database("status")["containers"] == [
            {"state": "running", "health": "healthy"}
        ]
