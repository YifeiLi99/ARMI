from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


class WindowsCredentialAclTests(unittest.TestCase):
    def run_checker(self, sddl: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "pwsh",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-File",
                "tools/check_windows_credential_acl.ps1",
                "-Sddl",
                sddl,
                "-ExpectedReaderSid",
                "S-1-5-80-12345",
            ],
            cwd=Path.cwd(),
            check=False,
            capture_output=True,
            text=True,
        )

    def test_policy_requires_per_environment_activation(self) -> None:
        completed = subprocess.run(
            [
                "pwsh",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-File",
                "tools/check_windows_credential_acl.ps1",
                "-PolicyOnly",
            ],
            cwd=Path.cwd(),
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("per-environment activation required", completed.stdout)

    def test_synthetic_exact_matrix_passes(self) -> None:
        completed = self.run_checker(
            "D:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;0x20089;;;S-1-5-80-12345)"
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_broad_principal_and_wrong_rights_are_rejected(self) -> None:
        cases = (
            (
                "D:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;FR;;;WD)(A;;0x20089;;;S-1-5-80-12345)",
                "SEC-ACL-BROAD",
            ),
            (
                "D:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;FA;;;S-1-5-80-12345)",
                "SEC-ACL-RIGHTS",
            ),
        )
        for sddl, code in cases:
            with self.subTest(code=code):
                completed = self.run_checker(sddl)
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn(code, completed.stderr)

    def test_environment_activation_record_requires_real_passes(self) -> None:
        descriptor = "D:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;0x20089;;;S-1-5-80-12345)"
        record = {
            "schema_version": "armi.windows-credential-acl-activation.v1",
            "active": True,
            "descriptors": [
                {"sddl": descriptor, "reader_sid": "S-1-5-80-12345"} for _ in range(3)
            ],
            "access_matrix": [{"passed": True}],
            "process_tokens": [{"passed": True, "sid": "S-1-5-80-12345"}],
        }
        with tempfile.TemporaryDirectory(dir=Path.cwd() / ".tmp") as temporary:
            path = Path(temporary) / "activation.json"
            path.write_text(json.dumps(record), encoding="utf-8", newline="\n")
            completed = subprocess.run(
                [
                    "pwsh",
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-File",
                    "tools/check_windows_credential_acl.ps1",
                    "-ActivationRecord",
                    str(path),
                ],
                cwd=Path.cwd(),
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("environment activation verified", completed.stdout)

    def test_elevated_rehearsal_uses_exact_pwsh_and_persists_failure_code(
        self,
    ) -> None:
        elevated = Path("tools/invoke_s045_elevated.ps1").read_text(encoding="utf-8")
        launcher = Path("tools/run_s045_rehearsal.py").read_text(encoding="utf-8")

        self.assertIn("Join-Path $PSHOME 'pwsh.exe'", elevated)
        self.assertIn("System32/WindowsPowerShell/v1.0/powershell.exe", elevated)
        self.assertIn("Invoke-As $role $probeShell", elevated)
        self.assertNotIn("Invoke-As $role 'pwsh'", elevated)
        self.assertIn("S045-$($Label.ToUpperInvariant())-START", elevated)
        self.assertIn("armi.s045-elevated-failure.v1", elevated)
        self.assertIn('Path(f"{summary_path}.failure.json")', launcher)


if __name__ == "__main__":
    unittest.main()
