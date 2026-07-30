from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from armi_kernel.application import BirthResult
from armi_kernel.contracts import Digest
from armi_runtime.cli import main
from armi_runtime.composition.environment import prepare_environment
from armi_runtime.interfaces.creator_contract import BootstrapCodeResponse

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
    def test_environment_root_preflight_and_redacted_config_check(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_environment(root)
            prepared = prepare_environment(root, environment={})
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
        self.assertEqual(
            result["effective_config_digest"],
            prepared.effective.digest.to_wire(),
        )
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
                patch("armi_runtime.cli.run_runtime", return_value=0) as runner,
                redirect_stdout(output),
            ):
                exit_code = main(
                    ("runtime", "start", "--environment-root", str(root.resolve()))
                )

        self.assertEqual(exit_code, 0)
        self.assertEqual(output.getvalue(), "")
        runner.assert_called_once()

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

    def test_creator_session_issue_requires_tty_and_prints_only_code(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_environment(root, creator_locator=True)
            output = io.StringIO()
            response = BootstrapCodeResponse(
                contract_version="1.0",
                bootstrap_code=f"bootstrap-v1.{'b' * 22}",
                expires_at="2026-07-30T18:00:00.000000Z",
            )
            with (
                patch.dict(os.environ, {}, clear=True),
                patch.object(output, "isatty", return_value=True),
                patch(
                    "armi_runtime.cli.issue_browser_bootstrap",
                    return_value=response,
                ) as issue,
                redirect_stdout(output),
            ):
                exit_code = main(
                    (
                        "creator-session",
                        "issue",
                        "--environment-root",
                        str(root.resolve()),
                    )
                )

        self.assertEqual(exit_code, 0)
        self.assertEqual(output.getvalue().strip(), response.bootstrap_code)
        issue.assert_called_once()

    def test_creator_session_issue_rejects_redirected_stdout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_environment(root, creator_locator=True)
            output = io.StringIO()
            errors = io.StringIO()
            with (
                patch.dict(os.environ, {}, clear=True),
                redirect_stdout(output),
                redirect_stderr(errors),
            ):
                exit_code = main(
                    (
                        "creator-session",
                        "issue",
                        "--environment-root",
                        str(root.resolve()),
                    )
                )
        self.assertEqual(exit_code, 2)
        self.assertEqual(json.loads(errors.getvalue())["code"], "CLI-CREATOR-TTY")
        self.assertEqual(output.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
