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
                result = manager.start()

            self.assertEqual(result["status"], "started")
            options = popen.call_args.kwargs
            self.assertIs(options["stdin"], subprocess.DEVNULL)
            self.assertIs(options["stdout"], subprocess.DEVNULL)
            self.assertIs(options["stderr"], subprocess.DEVNULL)
            if os.name == "nt":
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


if __name__ == "__main__":
    unittest.main()
