import json
import os
import secrets
import socket
import subprocess
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid7

import pytest
from armi_local_control import (
    NativePostgreSQL,
    PostgreSQLControlBinding,
)
from armi_local_control.runtime_errors import RuntimeViolation


def cluster(root: Path, *, port: int = 15432) -> NativePostgreSQL:
    return NativePostgreSQL(
        PostgreSQLControlBinding(
            ownership="exclusive",
            installation_root=root / "pgsql",
            data_directory=root / "postgresql/data",
            port=port,
        ),
        environment_root=root,
        environment_id=str(uuid7()),
    )


def test_cluster_cannot_escape_environment(tmp_path: Path) -> None:
    with pytest.raises(RuntimeViolation, match="LOCAL-POSTGRESQL-BOUNDARY"):
        NativePostgreSQL(
            PostgreSQLControlBinding(
                ownership="exclusive",
                installation_root=tmp_path / "pgsql",
                data_directory=tmp_path.parent / "foreign-data",
                port=15432,
            ),
            environment_root=tmp_path,
            environment_id=str(uuid7()),
        )


def test_initialization_preserves_unknown_nonempty_cluster(tmp_path: Path) -> None:
    manager = cluster(tmp_path)
    manager.data.mkdir(parents=True)
    marker = manager.data / "important"
    marker.write_bytes(b"existing data")
    with (
        patch("armi_local_control.native_postgresql.private_directory"),
        patch.object(manager, "_run") as run,
        pytest.raises(RuntimeViolation, match="LOCAL-POSTGRESQL-NONEMPTY"),
    ):
        manager.initialize(username="bootstrap", password=secrets.token_urlsafe(32))
    run.assert_not_called()
    assert marker.read_bytes() == b"existing data"


def test_failed_initial_preparation_can_stop_without_initializing(
    tmp_path: Path,
) -> None:
    manager = cluster(tmp_path)
    with patch.object(manager, "_run") as run:
        assert manager.execute("stop")["status"] == "stopped"
        with pytest.raises(RuntimeViolation, match="NOT-INITIALIZED"):
            manager.execute("start")
        manager.data.mkdir(parents=True)
        (manager.data / "unknown").write_bytes(b"preserve")
        with pytest.raises(RuntimeViolation, match="NOT-INITIALIZED"):
            manager.execute("stop")
    run.assert_not_called()
    assert (manager.data / "unknown").read_bytes() == b"preserve"


def test_occupied_port_never_connects_or_starts_database(tmp_path: Path) -> None:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        manager = cluster(tmp_path, port=listener.getsockname()[1])
        manager.control.mkdir(parents=True)
        with (
            patch.object(manager, "_identity"),
            patch.object(manager, "_run") as run,
            pytest.raises(RuntimeViolation, match="LOCAL-POSTGRESQL-PORT"),
        ):
            manager.execute("start")
        run.assert_not_called()


def test_foreign_system_identifier_prevents_stop(tmp_path: Path) -> None:
    manager = cluster(tmp_path)
    manager.control.mkdir(parents=True)
    manager.identity_path.write_text(
        json.dumps(
            {
                "schema_kind": "armi.native-postgresql",
                "environment_id": manager.environment_id,
                "data_directory": str(manager.data),
                "port": manager.binding.port,
                "postgresql_version": "18.4",
                "system_identifier": "123",
            }
        ),
        encoding="utf-8",
    )
    with (
        patch.object(manager, "_system_identifier", return_value="456"),
        patch.object(manager, "_process") as process,
        pytest.raises(RuntimeViolation, match="LOCAL-POSTGRESQL-IDENTITY"),
    ):
        manager.execute("stop")
    process.assert_not_called()


def test_packaged_server_waits_for_its_own_ready_pid(tmp_path: Path) -> None:
    manager = cluster(tmp_path)
    manager.data.mkdir(parents=True)
    process = Mock(pid=123, poll=Mock(return_value=None))
    pid_file = manager.data / "postmaster.pid"
    pid_file.write_text("999\ndata\n0\n15432\n\n\n\nready\n", encoding="utf-8")

    def ready(_):
        pid_file.write_text("123\ndata\n0\n15432\n\n\n\nready\n", encoding="utf-8")

    with (
        patch(
            "armi_local_control.native_postgresql.spawn_owned", return_value=process
        ) as spawn,
        patch(
            "armi_local_control.native_postgresql.time.sleep", side_effect=ready
        ) as sleep,
    ):
        manager._start_packaged()
    sleep.assert_called_once()
    assert spawn.call_args.args[0] == [
        str(manager.binding.installation_root / "bin/postgres.exe"),
        "-D",
        str(manager.data),
    ]
    assert spawn.call_args.kwargs["environment_id"] == manager.environment_id


def test_packaged_server_early_exit_is_not_ready(tmp_path: Path) -> None:
    manager = cluster(tmp_path)
    manager.control.mkdir(parents=True)
    with (
        patch(
            "armi_local_control.native_postgresql.spawn_owned",
            return_value=Mock(poll=Mock(return_value=1)),
        ),
        pytest.raises(RuntimeViolation, match="LOCAL-POSTGRESQL-FAILED"),
    ):
        manager._start_packaged()


def test_database_timeout_never_exposes_subprocess_output(tmp_path: Path) -> None:
    manager = cluster(tmp_path)
    executable = manager.binding.installation_root / "bin/pg_ctl.exe"
    executable.parent.mkdir(parents=True)
    executable.touch()
    with (
        patch(
            "armi_local_control.native_postgresql.subprocess.run",
            side_effect=subprocess.TimeoutExpired("pg_ctl", 1, output=b"secret"),
        ),
        pytest.raises(RuntimeViolation) as error,
    ):
        manager._run("pg_ctl", "start")
    assert error.value.code == "LOCAL-POSTGRESQL-UNKNOWN"
    assert "secret" not in str(error.value)


@pytest.mark.skipif(os.name != "nt", reason="Windows PostgreSQL filesystem encoding")
def test_postmaster_identity_uses_managed_utf8_filesystem_encoding(
    tmp_path: Path,
) -> None:
    manager = cluster(tmp_path / "验收 with spaces")
    manager.data.mkdir(parents=True)
    started = 1_789_000_000
    (manager.data / "postmaster.pid").write_text(
        f"4321\n{manager.data.as_posix()}\n{started}\n15432\n",
        encoding="utf-8",
    )
    identity = Mock(
        executable_identity=os.path.normcase(
            str(manager.binding.installation_root / "bin/postgres.exe")
        ),
        creation_time_microseconds=started * 1_000_000,
    )
    with (
        patch(
            "armi_local_control.native_postgresql.ManagedProcessIdentity.capture",
            return_value=identity,
        ),
        patch("armi_local_control.native_postgresql.psutil.Process") as process,
    ):
        process.return_value.cmdline.return_value = [
            "postgres.exe",
            "-D",
            str(manager.data),
        ]
        assert manager._process() is identity
