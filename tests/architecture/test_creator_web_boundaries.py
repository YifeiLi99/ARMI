"""Stable negative and positive Creator source boundary tests."""

from __future__ import annotations

import unittest
from pathlib import Path

from tools.check_creator_web import analyze_source, check_repository

ROOT = Path(__file__).resolve().parents[2]


class CreatorWebBoundaryTests(unittest.TestCase):
    def assert_rejected(self, source: str, expected: str) -> None:
        violations = analyze_source(source, path="<creator-sample>.tsx")
        self.assertIn(expected, {item.code for item in violations})

    def test_current_creator_satisfies_boundaries(self) -> None:
        self.assertEqual(check_repository(ROOT), [])

    def test_network_activity_is_rejected(self) -> None:
        self.assert_rejected(
            'fetch("/v1/runtime/status");\n',
            "SEC-WEB-NETWORK",
        )

    def test_browser_storage_is_rejected(self) -> None:
        self.assert_rejected(
            'sessionStorage.setItem("token", value);\n',
            "SEC-WEB-STORAGE",
        )

    def test_dynamic_html_is_rejected(self) -> None:
        self.assert_rejected(
            "const view = { dangerouslySetInnerHTML: payload };\n",
            "SEC-WEB-DYNAMIC",
        )

    def test_external_url_is_rejected(self) -> None:
        self.assert_rejected(
            'const endpoint = "https://example.invalid";\n',
            "SEC-WEB-EXTERNAL",
        )

    def test_global_store_is_rejected(self) -> None:
        self.assert_rejected(
            "const globalStore = createStore();\n",
            "ARC-WEB-GLOBAL-STORE",
        )


if __name__ == "__main__":
    unittest.main()
