from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

from armi_kernel.application import BirthResult
from armi_kernel.contracts import Digest
from armi_runtime.cli import main
from armi_runtime.composition.environment import prepare_environment

ENVIRONMENT_ID = "01980f7d-7b8f-7e2a-8a11-2ab8e1234567"


def make_environment(
    root: Path,
    *,
    port: int = 45678,
    creator_locator: bool = False,
) -> None:
    data = root / "data"
    secrets = root / "secrets"
    data.mkdir()
    secrets.mkdir()
    normalized_data = data.resolve().as_posix()
    lines = [
        "[environment]",
        f'environment_id = "{ENVIRONMENT_ID}"',
        f'data_root = "{normalized_data}"',
        "",
        "[creator]",
        f"port = {port}",
        "",
    ]
    if creator_locator:
        lines.extend(
            (
                "[secret_locators]",
                '"creator.bearer" = "env:ARMI_SECRET_CREATOR"',
                "",
            )
        )
    (root / "environment.toml").write_text(
        "\n".join(lines),
        encoding="utf-8",
        newline="\n",
    )


class RuntimeCliTests(unittest.TestCase):
    def test_unknown_armi_environment_returns_safe_configuration_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_environment(root)
            error = io.StringIO()
            with (
                patch.dict(
                    os.environ,
                    {"ARMI_UNREGISTERED_OVERRIDE": "private-value"},
                    clear=True,
                ),
                redirect_stderr(error),
            ):
                exit_code = main(
                    ("config", "check", "--environment-root", str(root.resolve()))
                )

        self.assertEqual(exit_code, 2)
        failure = json.loads(error.getvalue())
        self.assertEqual(failure["code"], "CFG-UNKNOWN-ENV")
        self.assertNotIn("private-value", error.getvalue())

    def test_environment_root_preflight_and_redacted_config_check(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_environment(root)
            output = io.StringIO()
            with (
                patch.dict(os.environ, {}, clear=True),
                redirect_stdout(output),
            ):
                exit_code = main(
                    ("config", "check", "--environment-root", str(root.resolve()))
                )

        result = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(result["status"], "pass")
        self.assertNotIn("effective_config_digest", result)
        self.assertEqual(
            result["config"]["environment"]["data_root"],
            {"configured": True},
        )
        self.assertNotIn(str(root), output.getvalue())

    def test_missing_layout_is_rejected_without_echoing_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = io.StringIO()
            with (
                patch.dict(os.environ, {}, clear=True),
                redirect_stderr(output),
            ):
                exit_code = main(
                    ("config", "check", "--environment-root", str(root.resolve()))
                )

        failure = json.loads(output.getvalue())
        self.assertEqual(exit_code, 2)
        self.assertEqual(failure["code"], "CFG-ENV-FILE")
        self.assertNotIn(str(root), output.getvalue())

    def test_runtime_command_uses_same_preflight_and_keeps_stdout_empty(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_environment(root)
            output = io.StringIO()
            with (
                patch.dict(os.environ, {}, clear=True),
                patch(
                    "armi_runtime.cli.prepare_environment",
                    wraps=prepare_environment,
                ) as prepare,
                patch("armi_runtime.cli.run_runtime", return_value=0) as runner,
                redirect_stdout(output),
            ):
                exit_code = main(
                    ("runtime", "start", "--environment-root", str(root.resolve()))
                )

        self.assertEqual(exit_code, 0)
        self.assertEqual(output.getvalue(), "")
        runner.assert_called_once()
        assert prepare.call_args.kwargs["credential_scope"] == {
            "database.runtime": "database.runtime",
            "creator.bootstrap.verify": "creator.bearer",
            "creator.timeline.cursor": "creator.bearer",
            "model.request": "model.ark_api_key",
            "web.search": "model.ark_api_key",
            "codex.runner.auth": "codex.auth_json",
            "channel.qq.napcat.api": "channel.qq.napcat_access_token",
            "channel.qq.napcat.events": "channel.qq.napcat_event_secret",
        }

    def test_background_start_uses_process_manager_and_safe_json(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_environment(root)
            output = io.StringIO()
            with (
                patch.dict(os.environ, {}, clear=True),
                patch("armi_runtime.cli.RuntimeProcessManager") as manager_type,
                redirect_stdout(output),
            ):
                manager_type.return_value.start.return_value = {
                    "status": "started",
                    "pid": 1234,
                    "runtime": {"runtime_state": "ready"},
                }
                exit_code = main(("start", "--environment-root", str(root.resolve())))

        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "started")
        manager_type.return_value.start.assert_called_once_with()

    def test_background_start_forwards_creator_resource_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            resources = root / "creator-web-resources"
            resources.mkdir()
            make_environment(root)
            with (
                patch.dict(os.environ, {}, clear=True),
                patch("armi_runtime.cli.RuntimeProcessManager") as manager_type,
                redirect_stdout(io.StringIO()),
            ):
                manager_type.return_value.start.return_value = {
                    "status": "started",
                    "pid": 1234,
                    "runtime": {"runtime_state": "ready"},
                }
                exit_code = main(
                    (
                        "start",
                        "--environment-root",
                        str(root.resolve()),
                        "--creator-web-resources",
                        str(resources.resolve()),
                    )
                )

        self.assertEqual(exit_code, 0)
        manager_type.return_value.start.assert_called_once_with(
            creator_web_resources=resources.resolve()
        )

    def test_background_status_defaults_to_current_environment_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_environment(root)
            output = io.StringIO()
            with (
                patch.dict(os.environ, {}, clear=True),
                patch("armi_runtime.cli.Path.cwd", return_value=root.resolve()),
                patch(
                    "armi_runtime.cli.prepare_environment", wraps=prepare_environment
                ) as prepare,
                patch("armi_runtime.cli.RuntimeProcessManager") as manager_type,
                redirect_stdout(output),
            ):
                manager_type.return_value.status.return_value = {
                    "status": "stopped",
                    "pid": None,
                }
                exit_code = main(("status",))

        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "stopped")
        self.assertEqual(prepare.call_args.kwargs["credential_scope"], {})

    def test_background_status_accepts_dedicated_environment_root_locator(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_environment(root)
            output = io.StringIO()
            with (
                patch.dict(
                    os.environ,
                    {"ARMI_ENVIRONMENT_ROOT": str(root.resolve())},
                    clear=True,
                ),
                patch(
                    "armi_runtime.cli.prepare_environment", wraps=prepare_environment
                ) as prepare,
                patch("armi_runtime.cli.RuntimeProcessManager") as manager_type,
                redirect_stdout(output),
            ):
                manager_type.return_value.status.return_value = {
                    "status": "stopped",
                    "pid": None,
                }
                exit_code = main(("status",))

        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "stopped")
        self.assertNotIn(
            "ARMI_ENVIRONMENT_ROOT",
            prepare.call_args.kwargs["environment"],
        )

    def test_creator_send_uses_runtime_control_without_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_environment(root)
            output = io.StringIO()
            with (
                patch.dict(os.environ, {}, clear=True),
                patch(
                    "armi_runtime.cli.prepare_environment", wraps=prepare_environment
                ) as prepare,
                patch("armi_runtime.cli.RuntimeProcessManager") as manager_type,
                redirect_stdout(output),
            ):
                manager_type.return_value.send_creator_input.return_value = {
                    "status": "succeeded",
                    "interaction_id": "interaction-1",
                    "newly_accepted": True,
                }
                exit_code = main(
                    (
                        "creator",
                        "send",
                        "--environment-root",
                        str(root.resolve()),
                        "--message",
                        "你好, ARMI",
                        "--idempotency-key",
                        "automation-message-1",
                    )
                )

        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "succeeded")
        self.assertEqual(prepare.call_args.kwargs["credential_scope"], {})
        manager_type.return_value.send_creator_input.assert_called_once_with(
            "你好, ARMI",
            idempotency_key="automation-message-1",
        )

    def test_creator_send_can_read_utf8_message_from_stdin(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_environment(root)
            with (
                patch.dict(os.environ, {}, clear=True),
                patch("armi_runtime.cli.sys.stdin", io.StringIO("来自标准输入")),
                patch("armi_runtime.cli.RuntimeProcessManager") as manager_type,
                redirect_stdout(io.StringIO()),
            ):
                manager_type.return_value.send_creator_input.return_value = {
                    "status": "succeeded"
                }
                exit_code = main(
                    (
                        "creator",
                        "send",
                        "--environment-root",
                        str(root.resolve()),
                        "--message-file",
                        "-",
                    )
                )

        self.assertEqual(exit_code, 0)
        manager_type.return_value.send_creator_input.assert_called_once_with(
            "来自标准输入",
            idempotency_key=None,
        )

    def test_birth_command_is_explicit_and_returns_only_stable_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_environment(root)
            output = io.StringIO()
            result = BirthResult(
                UUID("01980f7d-7b8f-7e2a-8a11-2ab8e1234568"),
                UUID("01980f7d-7b8f-7e2a-8a11-2ab8e1234569"),
                UUID("01980f7d-7b8f-7e2a-8a11-2ab8e1234570"),
                Digest.from_bytes(b"request"),
                True,
            )
            with (
                patch.dict(os.environ, {}, clear=True),
                patch(
                    "armi_runtime.cli.execute_birth",
                    return_value=result,
                ) as birth,
                redirect_stdout(output),
            ):
                exit_code = main(
                    (
                        "bootstrap",
                        "birth",
                        "--environment-root",
                        str(root.resolve()),
                    )
                )

        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "applied")
        birth.assert_called_once()

    def test_artifact_cleanup_defaults_to_read_only_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_environment(root)
            output = io.StringIO()
            report = SimpleNamespace(
                safe_view=lambda: {
                    "schema_version": "armi.artifact-report.v1",
                    "status": "dry_run",
                    "counts": {},
                    "findings": [],
                }
            )
            with (
                patch.dict(os.environ, {}, clear=True),
                patch(
                    "armi_runtime.cli.prepare_environment",
                    wraps=prepare_environment,
                ) as prepare,
                patch(
                    "armi_runtime.cli.run_artifact_retention",
                    return_value=report,
                ) as cleanup,
                redirect_stdout(output),
            ):
                exit_code = main(
                    (
                        "artifacts",
                        "cleanup",
                        "--environment-root",
                        str(root.resolve()),
                    )
                )

        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "dry_run")
        self.assertEqual(
            prepare.call_args.kwargs["credential_scope"],
            {"database.artifact-maintenance": "database.runtime"},
        )
        cleanup.assert_awaited_once()
        await_args = cleanup.await_args
        if await_args is None:
            self.fail("artifact cleanup was not awaited")
        self.assertFalse(await_args.kwargs["apply"])

    def test_database_maintenance_requires_explicit_apply_and_scoped_migrator(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_environment(root)
            with (
                redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit) as missing_apply,
            ):
                main(
                    (
                        "db",
                        "maintain",
                        "--environment-root",
                        str(root.resolve()),
                    )
                )
            self.assertEqual(missing_apply.exception.code, 2)
            output = io.StringIO()
            report = SimpleNamespace(
                safe_view=lambda: {
                    "schema_version": "armi.database-maintenance.v1",
                    "status": "applied",
                    "table_count": 42,
                }
            )
            with (
                patch.dict(os.environ, {}, clear=True),
                patch(
                    "armi_runtime.cli.prepare_environment",
                    wraps=prepare_environment,
                ) as prepare,
                patch(
                    "armi_runtime.cli.run_database_maintenance",
                    return_value=report,
                ) as maintain,
                redirect_stdout(output),
            ):
                exit_code = main(
                    (
                        "db",
                        "maintain",
                        "--environment-root",
                        str(root.resolve()),
                        "--apply",
                    )
                )

        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "applied")
        self.assertEqual(
            prepare.call_args.kwargs["credential_scope"],
            {"database.maintenance": "database.migrator"},
        )
        maintain.assert_called_once()

    def test_schema_migration_requires_apply_and_scoped_migrator(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_environment(root)
            with (
                redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit) as missing_apply,
            ):
                main(
                    (
                        "db",
                        "migrate",
                        "--environment-root",
                        str(root.resolve()),
                    )
                )
            self.assertEqual(missing_apply.exception.code, 2)
            output = io.StringIO()
            report = SimpleNamespace(
                safe_view=lambda: {
                    "status": "current",
                    "table_count": 43,
                    "current_revision": "0000",
                    "head_revision": "0000",
                }
            )
            with (
                patch.dict(os.environ, {}, clear=True),
                patch(
                    "armi_runtime.cli.prepare_environment",
                    wraps=prepare_environment,
                ) as prepare,
                patch(
                    "armi_runtime.cli.migrate_operator_schema",
                    return_value=report,
                ) as migrate,
                redirect_stdout(output),
            ):
                exit_code = main(
                    (
                        "db",
                        "migrate",
                        "--environment-root",
                        str(root.resolve()),
                        "--apply",
                    )
                )
        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "current")
        self.assertEqual(
            prepare.call_args.kwargs["credential_scope"],
            {"database.migrate": "database.migrator"},
        )
        migrate.assert_called_once()

    def test_capacity_baseline_is_read_only_and_returns_attention_exit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_environment(root)
            output = io.StringIO()
            report = SimpleNamespace(
                status="attention",
                safe_view=lambda: {
                    "schema_version": "armi.runtime-capacity-baseline.v1",
                    "status": "attention",
                    "issue_codes": ["CAPACITY-RSS-GROWTH"],
                },
            )
            with (
                patch.dict(os.environ, {}, clear=True),
                patch(
                    "armi_runtime.cli.prepare_environment",
                    wraps=prepare_environment,
                ) as prepare,
                patch(
                    "armi_runtime.cli.RuntimeProcessManager.status",
                    return_value={"status": "running"},
                ),
                patch(
                    "armi_runtime.cli.run_runtime_capacity_baseline",
                    return_value=report,
                ) as baseline,
                redirect_stdout(output),
            ):
                exit_code = main(
                    (
                        "capacity",
                        "baseline",
                        "--environment-root",
                        str(root.resolve()),
                        "--duration-seconds",
                        "30",
                        "--sample-interval-seconds",
                        "3",
                    )
                )

        self.assertEqual(exit_code, 4)
        self.assertEqual(json.loads(output.getvalue())["status"], "attention")
        self.assertEqual(prepare.call_args.kwargs["credential_scope"], {})
        self.assertEqual(baseline.call_args.kwargs["duration_seconds"], 30)
        self.assertEqual(baseline.call_args.kwargs["sample_interval_seconds"], 3)


if __name__ == "__main__":
    unittest.main()
