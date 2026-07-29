from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from armi_runtime.cli import main
from armi_runtime.composition.environment import prepare_environment

ENVIRONMENT_ID = "01980f7d-7b8f-7e2a-8a11-2ab8e1234567"


def make_environment(root: Path, *, port: int = 45678) -> None:
    data = root / "data"
    secrets = root / "secrets"
    data.mkdir()
    secrets.mkdir()
    normalized_data = data.resolve().as_posix()
    (root / "environment.toml").write_text(
        "\n".join(
            (
                "[environment]",
                f'environment_id = "{ENVIRONMENT_ID}"',
                f'data_root = "{normalized_data}"',
                "",
                "[creator]",
                f"port = {port}",
                "",
            )
        ),
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


if __name__ == "__main__":
    unittest.main()
