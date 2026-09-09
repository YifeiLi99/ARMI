from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from armi_runtime.composition.environment import prepare_environment
from armi_runtime.runtime_entrypoint import main

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
        "environment:",
        f"  environment_id: {ENVIRONMENT_ID}",
        f'  data_root: "{normalized_data}"',
        "creator:",
        f"  port: {port}",
    ]
    if creator_locator:
        lines.extend(
            (
                "secret_locators:",
                "  creator.bearer: env:ARMI_SECRET_CREATOR",
            )
        )
    (root / "environment.yaml").write_text(
        "\n".join(lines),
        encoding="utf-8",
        newline="\n",
    )


class RuntimeCliTests(unittest.TestCase):
    def test_worker_rejects_public_business_commands(self) -> None:
        for command in (
            "config",
            "db",
            "bootstrap",
            "creator",
            "other-human",
            "reset",
            "stop",
        ):
            with (
                self.subTest(command=command),
                redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit) as error,
            ):
                main((command, "--environment-root", str(Path.cwd())))
            self.assertEqual(error.exception.code, 2)

    def test_worker_requires_explicit_root_and_forwards_web_resources(self) -> None:
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            main(("runtime", "start"))
        self.assertEqual(error.exception.code, 2)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_environment(root)
            resources = root / "web"
            with (
                patch.dict(os.environ, {}, clear=True),
                patch(
                    "armi_runtime.runtime_entrypoint.run_runtime", return_value=0
                ) as runner,
            ):
                self.assertEqual(
                    main(
                        (
                            "runtime",
                            "start",
                            "--environment-root",
                            str(root),
                            "--creator-web-resources",
                            str(resources),
                        )
                    ),
                    0,
                )
            self.assertEqual(
                runner.call_args.kwargs["creator_web_resources"], resources
            )

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
                    ("runtime", "start", "--environment-root", str(root.resolve()))
                )

        self.assertEqual(exit_code, 2)
        failure = json.loads(error.getvalue())
        self.assertEqual(failure["code"], "CFG-UNKNOWN-ENV")
        self.assertNotIn("private-value", error.getvalue())

    def test_missing_layout_is_rejected_without_echoing_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = io.StringIO()
            with (
                patch.dict(os.environ, {}, clear=True),
                redirect_stderr(output),
            ):
                exit_code = main(
                    ("runtime", "start", "--environment-root", str(root.resolve()))
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
                    "armi_runtime.runtime_entrypoint.prepare_environment",
                    wraps=prepare_environment,
                ) as prepare,
                patch(
                    "armi_runtime.runtime_entrypoint.run_runtime", return_value=0
                ) as runner,
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
            "data_rights.identity_token": "data_rights.identity_token_key",
            "model.request": "model.ark_api_key",
            "speech.recognition": "speech.volc_credentials",
            "web.search": "model.ark_api_key",
            "codex.runner.auth": "codex.auth_json",
            "channel.qq.napcat.api": "channel.qq.napcat_access_token",
            "channel.qq.napcat.events": "channel.qq.napcat_event_secret",
        }


if __name__ == "__main__":
    unittest.main()
