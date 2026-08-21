from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import Literal
from unittest.mock import Mock, patch

from armi_admin.cli import main
from armi_admin.mcp.contracts import AdminToolResult

ENVIRONMENT_ID = "018f3f4a-7b8c-7def-8abc-1234567890ab"


def _result(
    *,
    status: Literal[
        "succeeded", "rejected", "conflict", "failed", "unknown"
    ] = "succeeded",
    result: dict[str, object] | None = None,
) -> AdminToolResult[dict[str, object]]:
    return AdminToolResult[dict[str, object]](
        operation_id="019f3f4a-7b8c-7def-8abc-1234567890ab",
        status=status,
        result=result,
        error_code=None if status == "succeeded" else "ADMIN-RESET-REJECTED",
        started_at="2026-08-21T00:00:00Z",
        ended_at="2026-08-21T00:00:01Z",
    )


class AdminCliTests(unittest.TestCase):
    def test_reset_requires_explicit_apply(self) -> None:
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit) as rejected:
            main(("reset",))

        self.assertEqual(rejected.exception.code, 2)

    def test_reset_previews_then_applies_and_closes(self) -> None:
        config = SimpleNamespace(
            environment_id=ENVIRONMENT_ID,
            environment_incarnation=4,
            locator=object(),
            migrator_locator=object(),
            preview_locator=object(),
        )
        service = Mock()
        service.mutate.side_effect = (
            _result(result={"preview_token": "v1." + "a" * 64}),
            _result(
                result={
                    "environment_id": ENVIRONMENT_ID,
                    "previous_incarnation": 4,
                    "incarnation": 5,
                    "status": "reset",
                }
            ),
        )
        composition = SimpleNamespace(service=service, close=Mock())
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "admin.yaml"
            with (
                patch(
                    "armi_admin.cli.load_admin_config",
                    return_value=(config, config_path),
                ),
                patch("armi_admin.cli.AdminCredentialPort"),
                patch("armi_admin.cli.bootstrap_admin", return_value=composition),
                patch("builtins.print") as output,
            ):
                exit_code = main(("reset", "--apply"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            [call.args[0] for call in service.mutate.call_args_list],
            ["environment_reset_preview", "environment_reset"],
        )
        preview_request = service.mutate.call_args_list[0].args[1]
        reset_request = service.mutate.call_args_list[1].args[1]
        self.assertEqual(reset_request.preview_token, "v1." + "a" * 64)
        self.assertNotEqual(
            preview_request.idempotency_key, reset_request.idempotency_key
        )
        composition.close.assert_called_once_with()
        payload = json.loads(output.call_args.args[0])
        self.assertEqual(payload["result"]["incarnation"], 5)

    def test_reset_stops_after_rejected_preview(self) -> None:
        config = SimpleNamespace(
            environment_id=ENVIRONMENT_ID,
            environment_incarnation=4,
            locator=object(),
            migrator_locator=object(),
            preview_locator=object(),
        )
        service = Mock()
        service.mutate.return_value = _result(status="rejected")
        composition = SimpleNamespace(service=service, close=Mock())
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "admin.yaml"
            with (
                patch(
                    "armi_admin.cli.load_admin_config",
                    return_value=(config, config_path),
                ),
                patch("armi_admin.cli.AdminCredentialPort"),
                patch("armi_admin.cli.bootstrap_admin", return_value=composition),
                patch("builtins.print"),
            ):
                exit_code = main(("reset", "--apply"))

        self.assertEqual(exit_code, 3)
        service.mutate.assert_called_once()
        composition.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
