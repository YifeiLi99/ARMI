from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from armi_runtime.composition.runtime_errors import RuntimeViolation
from armi_runtime.composition.runtime_process import RuntimeProcessManager


class RuntimeProcessManagerTests(unittest.TestCase):
    def test_status_reports_stopped_without_process_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            root.mkdir(exist_ok=True)
            manager = RuntimeProcessManager(root, "environment-1")

            self.assertEqual(manager.status(), {"status": "stopped", "pid": None})

    def test_start_uses_detached_process_and_waits_for_control(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            creator_resources = root / "creator-web-resources"
            creator_resources.mkdir()
            manager = RuntimeProcessManager(root, "environment-1")
            process = Mock(pid=1234)
            process.poll.return_value = None

            def launch(*args: object, **kwargs: object) -> Mock:
                descriptor = root / "run" / "admin-control" / "runtime-control.json"
                descriptor.write_text("{}\n", encoding="utf-8", newline="\n")
                return process

            with (
                patch.object(
                    RuntimeProcessManager,
                    "status",
                    side_effect=(
                        {"status": "stopped", "pid": None},
                        {
                            "status": "running",
                            "pid": 1234,
                            "runtime": {"runtime_state": "ready"},
                        },
                    ),
                ),
                patch(
                    "armi_runtime.composition.runtime_process.subprocess.Popen",
                    side_effect=launch,
                ) as popen,
            ):
                result = manager.start(
                    creator_web_resources=creator_resources.resolve()
                )

            self.assertEqual(result["status"], "started")
            options = popen.call_args.kwargs
            command = popen.call_args.args[0]
            self.assertEqual(
                command[-2:],
                ("--creator-web-resources", str(creator_resources.resolve())),
            )
            self.assertIs(options["stdin"], subprocess.DEVNULL)
            self.assertIs(options["stdout"], subprocess.DEVNULL)
            self.assertIs(options["stderr"], subprocess.DEVNULL)
            if os.name == "nt":
                self.assertEqual(Path(command[0]).name, "pythonw.exe")
                self.assertTrue(options["creationflags"] & subprocess.DETACHED_PROCESS)
                self.assertTrue(
                    options["creationflags"] & subprocess.CREATE_NEW_PROCESS_GROUP
                )
                self.assertTrue(
                    options["creationflags"] & subprocess.CREATE_BREAKAWAY_FROM_JOB
                )
            state = json.loads(
                (root / "run" / "runtime-process.json").read_text(encoding="utf-8")
            )
            self.assertEqual(state["pid"], 1234)

    def test_start_rejects_missing_creator_resource_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manager = RuntimeProcessManager(root, "environment-1")
            with self.assertRaises(RuntimeViolation) as raised:
                manager.start(creator_web_resources=(root / "missing").resolve())

        self.assertEqual(raised.exception.code, "WEB-ASSET-ROOT")

    def test_spawn_failure_is_safe_and_cleans_control_material(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manager = RuntimeProcessManager(root, "environment-1")
            with (
                patch.object(
                    RuntimeProcessManager,
                    "status",
                    return_value={"status": "stopped", "pid": None},
                ),
                patch(
                    "armi_runtime.composition.runtime_process.subprocess.Popen",
                    side_effect=OSError("private detail"),
                ),
                self.assertRaises(RuntimeViolation) as raised,
            ):
                manager.start()

            self.assertEqual(raised.exception.code, "CLI-RUNTIME-START-FAILED")
            self.assertFalse(
                (root / "run" / "admin-control" / "runtime-control.token").exists()
            )

    def test_stop_drains_before_stopping(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manager = RuntimeProcessManager(root, "environment-1")
            calls: list[str] = []
            with (
                patch.object(
                    RuntimeProcessManager,
                    "status",
                    return_value={"status": "running", "pid": 1234, "runtime": {}},
                ),
                patch.object(
                    RuntimeProcessManager,
                    "_send_control",
                    side_effect=lambda command: calls.append(command) or {"result": {}},
                ),
                patch(
                    "armi_runtime.composition.runtime_process._pid_is_alive",
                    return_value=False,
                ),
            ):
                result = manager.stop()

            self.assertEqual(calls, ["drain", "stop"])
            self.assertEqual(result["status"], "stopped")

    def test_creator_input_uses_formal_control_command_and_stable_key(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manager = RuntimeProcessManager(root, "environment-1")
            with patch.object(
                RuntimeProcessManager,
                "_send_control",
                return_value={
                    "result": {
                        "interaction_id": "interaction-1",
                        "newly_accepted": True,
                    }
                },
            ) as send:
                result = manager.send_creator_input(
                    "你好, ARMI",
                    idempotency_key="automation-message-1",
                )

        send.assert_called_once_with(
            "input",
            {
                "message": "你好, ARMI",
                "idempotency_key": "automation-message-1",
            },
        )
        self.assertEqual(result["status"], "succeeded")
        self.assertTrue(result["newly_accepted"])

    def test_creator_input_rejects_invalid_message_before_control(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manager = RuntimeProcessManager(Path(temporary), "environment-1")
            with (
                patch.object(RuntimeProcessManager, "_send_control") as send,
                self.assertRaises(RuntimeViolation) as raised,
            ):
                manager.send_creator_input("   ")

        self.assertEqual(raised.exception.code, "CLI-CREATOR-INPUT")
        send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
