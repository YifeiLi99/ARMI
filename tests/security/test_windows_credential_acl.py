from __future__ import annotations

import subprocess
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

    def test_policy_is_explicitly_inactive_until_s035(self) -> None:
        completed = subprocess.run(
            [
                "pwsh",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-File",
                "tools/check_windows_credential_acl.ps1",
            ],
            cwd=Path.cwd(),
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("inactive until M0-S045", completed.stdout)

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


if __name__ == "__main__":
    unittest.main()
