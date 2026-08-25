from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import psutil
from armi_runtime.composition.process_identity import ManagedProcessIdentity
from armi_runtime.composition.runtime_errors import RuntimeViolation
from armi_runtime.composition.runtime_process import RuntimeProcessManager


class RuntimeProcessManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        original = ManagedProcessIdentity.capture.__func__

        def capture(
            cls: type[ManagedProcessIdentity],
            pid: int,
            *,
            environment_identity: str,
            incarnation: int,
            runtime_instance_id: str | None = None,
        ) -> ManagedProcessIdentity:
            if pid != 1234:
                return original(
                    cls,
                    pid,
                    environment_identity=environment_identity,
                    incarnation=incarnation,
                    runtime_instance_id=runtime_instance_id,
                )
            return cls(
                pid,
                1,
                "pythonw.exe",
                "sha256:" + "a" * 64,
                environment_identity,
                incarnation,
                runtime_instance_id,
            )

        patcher = patch.object(ManagedProcessIdentity, "capture", classmethod(capture))
        patcher.start()
        self.addCleanup(patcher.stop)

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
            self.assertNotIn("ALL_PROXY", options["env"])
            if os.name == "nt":
                self.assertEqual(Path(command[0]).name, "pythonw.exe")
                self.assertEqual(options["env"]["SYSTEMROOT"], os.environ["SYSTEMROOT"])
                self.assertEqual(
                    options["env"]["USERPROFILE"], os.environ["USERPROFILE"]
                )
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

    def test_start_refuses_verified_residual_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manager = RuntimeProcessManager(root, "environment-1")
            residual = Mock(spec=psutil.Process)
            residual.pid = 4321
            with (
                patch.object(
                    RuntimeProcessManager,
                    "status",
                    return_value={"status": "stopped", "pid": None},
                ),
                patch.object(
                    RuntimeProcessManager,
                    "_matching_runtime_processes",
                    return_value=[residual],
                ),
                patch(
                    "armi_runtime.composition.runtime_process.subprocess.Popen"
                ) as popen,
                self.assertRaises(RuntimeViolation) as raised,
            ):
                manager.start()

        self.assertEqual(raised.exception.code, "CLI-RUNTIME-RESIDUAL")
        popen.assert_not_called()

    def test_process_identity_requires_runtime_entry_and_exact_environment(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            manager = RuntimeProcessManager(root, "environment-1")
            matching = Mock(spec=psutil.Process)
            matching.cmdline.return_value = [
                "pythonw.exe",
                "-m",
                "armi_runtime.cli",
                "runtime",
                "start",
                "--environment-root",
                str(root),
            ]
            other_environment = Mock(spec=psutil.Process)
            other_environment.cmdline.return_value = [
                "pythonw.exe",
                "-m",
                "armi_runtime.cli",
                "runtime",
                "start",
                "--environment-root",
                str(root.parent / "other"),
            ]
            embedded_marker = Mock(spec=psutil.Process)
            embedded_marker.cmdline.return_value = [
                "python.exe",
                "-c",
                "print('not a Runtime')",
                "-m",
                "armi_runtime.cli",
                "runtime",
                "start",
                "--environment-root",
                str(root),
            ]

            self.assertTrue(manager._matches_runtime_process(matching))
            self.assertFalse(manager._matches_runtime_process(other_environment))
            self.assertFalse(manager._matches_runtime_process(embedded_marker))

    def test_restart_reaps_verified_residual_before_starting(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manager = RuntimeProcessManager(root, "environment-1")
            calls: list[str] = []
            with (
                patch.object(
                    RuntimeProcessManager,
                    "stop",
                    side_effect=lambda: calls.append("stop") or {"status": "stopped"},
                ),
                patch.object(
                    RuntimeProcessManager,
                    "_terminate_residual_runtime",
                    side_effect=lambda: calls.append("reap"),
                ),
                patch.object(
                    RuntimeProcessManager,
                    "_assert_no_residual_runtime",
                    side_effect=lambda: calls.append("verify"),
                ),
                patch.object(RuntimeProcessManager, "_clear_stale_files"),
                patch.object(
                    RuntimeProcessManager,
                    "start",
                    side_effect=lambda **_kwargs: (
                        calls.append("start") or {"status": "started"}
                    ),
                ),
            ):
                result = manager.restart()

        self.assertEqual(result["status"], "started")
        self.assertEqual(calls, ["stop", "reap", "verify", "start"])

    def test_restart_does_not_start_when_residual_cleanup_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manager = RuntimeProcessManager(Path(temporary), "environment-1")
            with (
                patch.object(
                    RuntimeProcessManager,
                    "stop",
                    return_value={"status": "stopped"},
                ),
                patch.object(
                    RuntimeProcessManager,
                    "_terminate_residual_runtime",
                    side_effect=RuntimeViolation(
                        "CLI-RUNTIME-RESIDUAL-STOP",
                        "private process detail",
                    ),
                ),
                patch.object(RuntimeProcessManager, "start") as start,
                self.assertRaises(RuntimeViolation) as raised,
            ):
                manager.restart()

        self.assertEqual(raised.exception.code, "CLI-RUNTIME-RESIDUAL-STOP")
        start.assert_not_called()

    def test_residual_cleanup_escalates_and_waits_for_verified_process(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manager = RuntimeProcessManager(Path(temporary), "environment-1")
            residual = Mock(spec=psutil.Process)
            residual.pid = 4321
            with (
                patch.object(
                    RuntimeProcessManager,
                    "_matching_runtime_processes",
                    return_value=[residual],
                ),
                patch.object(
                    RuntimeProcessManager,
                    "_matches_runtime_process",
                    return_value=True,
                ),
                patch(
                    "armi_runtime.composition.runtime_process.psutil.wait_procs",
                    side_effect=(([], [residual]), ([residual], [])),
                ) as wait,
            ):
                manager._terminate_residual_runtime()

        residual.terminate.assert_called_once_with()
        residual.kill.assert_called_once_with()
        self.assertEqual(wait.call_count, 2)

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

    def test_start_timeout_terminates_child_and_cleans_control_material(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manager = RuntimeProcessManager(root, "environment-1")
            process = Mock(pid=1234)
            process.poll.return_value = None
            process.wait.return_value = 0
            with (
                patch.object(
                    RuntimeProcessManager,
                    "status",
                    return_value={"status": "stopped", "pid": None},
                ),
                patch(
                    "armi_runtime.composition.runtime_process.subprocess.Popen",
                    return_value=process,
                ),
                patch(
                    "armi_runtime.composition.runtime_process._START_TIMEOUT_SECONDS",
                    0.0,
                ),
                self.assertRaises(RuntimeViolation) as raised,
            ):
                manager.start()

            self.assertEqual(raised.exception.code, "CLI-RUNTIME-START-TIMEOUT")
            process.terminate.assert_called_once_with()
            process.wait.assert_called_once_with(timeout=5.0)
            process.kill.assert_not_called()
            self.assertFalse((root / "run" / "runtime-process.json").exists())
            self.assertFalse(
                (root / "run" / "admin-control" / "runtime-control.token").exists()
            )

    def test_start_timeout_kills_child_that_ignores_termination(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manager = RuntimeProcessManager(root, "environment-1")
            process = Mock(pid=1234)
            process.poll.return_value = None
            process.wait.side_effect = (
                subprocess.TimeoutExpired("runtime", 5.0),
                0,
            )
            with (
                patch.object(
                    RuntimeProcessManager,
                    "status",
                    return_value={"status": "stopped", "pid": None},
                ),
                patch(
                    "armi_runtime.composition.runtime_process.subprocess.Popen",
                    return_value=process,
                ),
                patch(
                    "armi_runtime.composition.runtime_process._START_TIMEOUT_SECONDS",
                    0.0,
                ),
                self.assertRaises(RuntimeViolation) as raised,
            ):
                manager.start()

            self.assertEqual(raised.exception.code, "CLI-RUNTIME-START-TIMEOUT")
            process.terminate.assert_called_once_with()
            process.kill.assert_called_once_with()
            self.assertEqual(process.wait.call_count, 2)
            self.assertFalse((root / "run" / "runtime-process.json").exists())

    def test_start_timeout_reaps_a_real_never_ready_child(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manager = RuntimeProcessManager(root, "environment-1")
            real_popen = subprocess.Popen
            child: subprocess.Popen[bytes] | None = None

            def launch(*_args: object, **_kwargs: object) -> subprocess.Popen[bytes]:
                nonlocal child
                child = real_popen(
                    (sys.executable, "-c", "import time; time.sleep(30)"),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return child

            try:
                with (
                    patch.object(
                        RuntimeProcessManager,
                        "status",
                        return_value={"status": "stopped", "pid": None},
                    ),
                    patch(
                        "armi_runtime.composition.runtime_process.subprocess.Popen",
                        side_effect=launch,
                    ),
                    patch(
                        "armi_runtime.composition.runtime_process._START_TIMEOUT_SECONDS",
                        0.0,
                    ),
                    self.assertRaises(RuntimeViolation) as raised,
                ):
                    manager.start()
            finally:
                if child is not None and child.poll() is None:
                    child.kill()
                    child.wait(timeout=5)

            self.assertEqual(raised.exception.code, "CLI-RUNTIME-START-TIMEOUT")
            self.assertIsNotNone(child)
            assert child is not None
            self.assertIsNotNone(child.poll())
            self.assertFalse((root / "run" / "runtime-process.json").exists())

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

    def test_other_human_uses_authenticated_runtime_control(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manager = RuntimeProcessManager(Path(temporary), "environment-1")
            with patch.object(
                RuntimeProcessManager,
                "_send_control",
                return_value={"result": {"party_id": "party-1"}},
            ) as send:
                result = manager.other_human(
                    "party_register",
                    {"party_key": "friend-1", "display_label": "朋友"},
                )

        send.assert_called_once_with(
            "other_human",
            {
                "action": "party_register",
                "payload": {"party_key": "friend-1", "display_label": "朋友"},
            },
        )
        self.assertEqual(result, {"status": "succeeded", "party_id": "party-1"})


if __name__ == "__main__":
    unittest.main()
