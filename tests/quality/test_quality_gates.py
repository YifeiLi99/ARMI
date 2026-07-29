"""Prove stable failures for type, format, secret, and aggregation gates."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from tools.check_repository_hygiene import scan_paths
from tools.quality import Gate, GateResult, aggregate_exit_code, run_gate

ROOT = Path(__file__).resolve().parents[2]
VENV_PYTHON = ROOT / ".venv/Scripts/python.exe"
TOOL_ROOT = Path(os.environ.get("ARMI_TOOL_ROOT", ROOT / ".armi-tools"))
NODE = TOOL_ROOT / "installs/node/node-v24.18.0-win-x64/node.exe"


class QualityGateTests(unittest.TestCase):
    def run_sample(self, gate: Gate):
        return run_gate(gate, os.environ.copy())

    def test_earlier_failure_cannot_be_masked(self) -> None:
        results = [
            GateResult("PY-TYPE", "fail", 1, "injected failure"),
            GateResult("PY-TEST", "pass", 0, ""),
        ]
        self.assertEqual(aggregate_exit_code(results), 1)

    def test_missing_tool_is_blocked(self) -> None:
        missing = ROOT / ".tmp/quality/does-not-exist.exe"
        result = self.run_sample(Gate("QLT-MISSING", ("unused",), ROOT, (missing,)))
        self.assertEqual(result.status, "blocked")
        self.assertEqual(aggregate_exit_code([result]), 2)

    def test_python_format_error_fails_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            sample = Path(temporary) / "bad.py"
            sample.write_text("value={  'a':1}\n", encoding="utf-8")
            result = self.run_sample(
                Gate(
                    "PY-FORMAT",
                    (
                        str(VENV_PYTHON),
                        "-m",
                        "ruff",
                        "format",
                        "--check",
                        str(sample),
                    ),
                    ROOT,
                    (VENV_PYTHON,),
                )
            )
        self.assertEqual(result.gate_id, "PY-FORMAT")
        self.assertEqual(result.status, "fail")

    def test_python_type_error_fails_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "bad.py").write_text("value: str = 1\n", encoding="utf-8")
            (root / "pyrightconfig.json").write_text(
                '{"include":["bad.py"],"typeCheckingMode":"strict"}\n',
                encoding="utf-8",
            )
            pyright = ROOT / "tools/toolchain-node/node_modules/pyright/index.js"
            result = self.run_sample(
                Gate(
                    "PY-TYPE",
                    (
                        str(NODE),
                        str(pyright),
                        "--project",
                        str(root / "pyrightconfig.json"),
                    ),
                    ROOT,
                    (NODE, pyright),
                )
            )
        self.assertEqual(result.status, "fail")

    def test_typescript_type_error_fails_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "bad.ts").write_text("const value: string = 1;\n", encoding="utf-8")
            (root / "tsconfig.json").write_text(
                '{"compilerOptions":{"strict":true,"noEmit":true},'
                '"include":["bad.ts"]}\n',
                encoding="utf-8",
            )
            tsc = ROOT / "apps/armi-creator-web/node_modules/typescript/bin/tsc"
            result = self.run_sample(
                Gate(
                    "WEB-TYPE",
                    (
                        str(NODE),
                        str(tsc),
                        "--project",
                        str(root / "tsconfig.json"),
                    ),
                    ROOT,
                    (NODE, tsc),
                )
            )
        self.assertEqual(result.status, "fail")

    def test_frontend_format_error_fails_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            sample = Path(temporary) / "bad.ts"
            sample.write_text("const value={a:1}\n", encoding="utf-8")
            prettier = (
                ROOT / "apps/armi-creator-web/node_modules/prettier/bin/prettier.cjs"
            )
            result = self.run_sample(
                Gate(
                    "WEB-FORMAT",
                    (str(NODE), str(prettier), "--check", str(sample)),
                    ROOT,
                    (NODE, prettier),
                )
            )
        self.assertEqual(result.status, "fail")

    def test_dynamic_secret_and_personal_path_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            secret = "sk" + "-" + "A" * 24
            personal = "C:" + "\\Us" + "ers\\example\\file.txt"
            sample = root / "sample.txt"
            sample.write_text(f"{secret}\n{personal}\n", encoding="utf-8")
            codes = {item.code for item in scan_paths([sample], root)}
        self.assertIn("SEC-SECRET-TOKEN", codes)
        self.assertIn("SEC-PATH-PERSONAL", codes)


if __name__ == "__main__":
    unittest.main()
