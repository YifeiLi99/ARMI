"""Import each distribution with only its declared local dependency roots."""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KERNEL_SOURCE = ROOT / "packages/armi-kernel/src"
RUNTIME_SOURCE = ROOT / "apps/armi-runtime/src"
ADMIN_SOURCE = ROOT / "apps/armi-admin/src"
NAPCAT_SOURCE = ROOT / "packages/armi-channel-napcat/src"
QQ_ADAPTER_SOURCE = ROOT / "packages/armi-adapter-qq/src"


class PackageImportSmokeTests(unittest.TestCase):
    def run_isolated_import(self, source_roots: list[Path], script: str) -> None:
        path_setup = ", ".join(repr(str(path)) for path in source_roots)
        command = f"import sys; sys.path[:0] = [{path_setup}]; {script}"
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        result = subprocess.run(
            [sys.executable, "-B", "-c", command],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            result.returncode,
            0,
            msg=f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        )

    def test_kernel_imports_without_application_distributions(self) -> None:
        self.run_isolated_import(
            [KERNEL_SOURCE],
            "import armi_kernel; "
            "assert armi_kernel.__all__ == (); "
            "assert not any(name.startswith(('armi_runtime', 'armi_admin')) "
            "for name in sys.modules)",
        )

    def test_runtime_imports_with_kernel_but_without_admin(self) -> None:
        self.run_isolated_import(
            [RUNTIME_SOURCE, KERNEL_SOURCE],
            "import armi_runtime; "
            "assert armi_runtime.__all__ == (); "
            "assert not any(name.startswith('armi_admin') for name in sys.modules)",
        )

    def test_admin_imports_with_kernel_but_without_runtime(self) -> None:
        self.run_isolated_import(
            [ADMIN_SOURCE, KERNEL_SOURCE],
            "import armi_admin; "
            "assert armi_admin.__all__ == (); "
            "assert not any(name.startswith('armi_runtime') for name in sys.modules)",
        )

    def test_napcat_channel_imports_without_armi(self) -> None:
        self.run_isolated_import(
            [NAPCAT_SOURCE],
            "import armi_channel_napcat; "
            "assert not any(name.startswith('armi_kernel') for name in sys.modules)",
        )

    def test_qq_adapter_imports_only_public_dependencies(self) -> None:
        self.run_isolated_import(
            [QQ_ADAPTER_SOURCE, NAPCAT_SOURCE, KERNEL_SOURCE],
            "import armi_adapter_qq; "
            "assert not any(name.startswith(('armi_runtime', 'armi_admin')) "
            "for name in sys.modules)",
        )


if __name__ == "__main__":
    unittest.main()
