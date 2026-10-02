"""Process-query behavior owned by the local-control package."""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from unittest.mock import patch

import pytest
from armi_local_control.runtime_errors import RuntimeViolation
from armi_local_control.runtime_process import _pid_is_alive

pytestmark = pytest.mark.test_group("runtime")


class ProcessQueryTests(unittest.TestCase):
    def test_process_query_observes_real_child_exit(self) -> None:
        child = subprocess.Popen(
            (sys.executable, "-c", "import time; time.sleep(30)"),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        try:
            self.assertTrue(_pid_is_alive(child.pid))
            child.terminate()
            child.wait(timeout=5)
            self.assertFalse(_pid_is_alive(child.pid))
        finally:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=5)

    def test_posix_process_query_distinguishes_absence_from_denied_access(self) -> None:
        with (
            patch("armi_local_control.runtime_process.os.name", "posix"),
            patch("armi_local_control.runtime_process.os.kill") as query,
        ):
            query.side_effect = ProcessLookupError
            self.assertFalse(_pid_is_alive(1234))
            query.side_effect = PermissionError
            with self.assertRaises(RuntimeViolation) as raised:
                _pid_is_alive(1234)
            self.assertEqual(raised.exception.code, "CLI-RUNTIME-PROCESS-INSPECTION")
