from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from armi_runtime.composition.diagnostics import StructuredDiagnosticLog
from armi_runtime.composition.lifecycle import LifecycleController
from armi_runtime.interfaces.creator_contract import RuntimeState

_ENVIRONMENT = "01980f7d-7b8f-7e2a-8a11-2ab8e1234567"
_REASON = "RUNTIME_DIAGNOSTIC_FILE_LOG_UNAVAILABLE"


class _WriteFailure(io.StringIO):
    def write(self, value: str) -> int:
        raise OSError("private path and failure details")


class DiagnosticTests(unittest.TestCase):
    def test_initial_file_failure_uses_stderr_without_path_or_error(self) -> None:
        fallback = io.StringIO()
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(Path, "open", side_effect=OSError("private detail")):
                diagnostic = StructuredDiagnosticLog(
                    data_root=Path(temporary),
                    environment_id=_ENVIRONMENT,
                    instance_id="instance",
                    fallback=fallback,
                )
            self.assertEqual(diagnostic.status.mode, "stderr")
            self.assertEqual(diagnostic.status.reason_code, _REASON)
            diagnostic.emit("runtime.lifecycle.starting")
            diagnostic.close()
        output = fallback.getvalue()
        self.assertIn("runtime.lifecycle.starting", output)
        self.assertNotIn(temporary, output)
        self.assertNotIn("private detail", output)

    def test_runtime_write_failure_notifies_lifecycle_and_falls_back(self) -> None:
        fallback = io.StringIO()
        lifecycle = LifecycleController(environment_id=_ENVIRONMENT)
        lifecycle.start()
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(Path, "open", return_value=_WriteFailure()):
                diagnostic = StructuredDiagnosticLog(
                    data_root=Path(temporary),
                    environment_id=_ENVIRONMENT,
                    instance_id="instance",
                    fallback=fallback,
                    on_degraded=lifecycle.add_degradation,
                )
            diagnostic.emit("runtime.lifecycle.starting")
            snapshot = lifecycle.complete_startup(())
            diagnostic.close()
        self.assertEqual(snapshot.runtime_state, RuntimeState.DEGRADED)
        self.assertEqual(snapshot.reason_codes, (_REASON,))
        self.assertEqual(diagnostic.status.mode, "stderr")
        self.assertIn("runtime.lifecycle.starting", fallback.getvalue())

    def test_core_blockers_keep_runtime_blocked_when_log_degrades(self) -> None:
        lifecycle = LifecycleController(environment_id=_ENVIRONMENT)
        lifecycle.start()
        lifecycle.add_degradation(_REASON)
        snapshot = lifecycle.complete_startup(("RUNTIME_RECOVERY_NOT_IMPLEMENTED",))
        self.assertEqual(snapshot.runtime_state, RuntimeState.BLOCKED)
        self.assertIn(_REASON, snapshot.reason_codes)


if __name__ == "__main__":
    unittest.main()
