"""Negative and positive tests for the M0 package boundaries."""

from __future__ import annotations

import unittest
from pathlib import Path

from tools.check_workspace_boundaries import (
    analyze_source,
    check_repository,
    exit_code_for,
)

ROOT = Path(__file__).resolve().parents[2]
PUBLIC_EXPORTS = {
    "armi_kernel": frozenset(),
    "armi_kernel.application": frozenset({"PublicPort"}),
    "armi_kernel.contracts": frozenset({"PublicContract"}),
}


class WorkspaceBoundaryTests(unittest.TestCase):
    def analyze(
        self,
        source: str,
        *,
        module: str,
        distribution: str,
        is_package: bool = False,
    ):
        return analyze_source(
            source,
            module=module,
            distribution=distribution,
            path="<boundary-sample>",
            is_package=is_package,
            public_exports=PUBLIC_EXPORTS,
        )

    def assert_rejected(self, violations, expected_code: str) -> None:
        self.assertIn(expected_code, {violation.code for violation in violations})
        self.assertEqual(exit_code_for(violations), 1)

    def test_current_repository_satisfies_boundaries(self) -> None:
        self.assertEqual(check_repository(ROOT), [])

    def test_explicit_kernel_application_export_is_allowed(self) -> None:
        violations = self.analyze(
            "from armi_kernel.application import PublicPort\n",
            module="armi_runtime.adapters.example",
            distribution="armi-runtime",
        )
        self.assertEqual(violations, [])
        self.assertEqual(exit_code_for(violations), 0)

    def test_runtime_cannot_import_admin(self) -> None:
        violations = self.analyze(
            "from armi_admin import application\n",
            module="armi_runtime.composition.example",
            distribution="armi-runtime",
        )
        self.assert_rejected(violations, "ARC-SURFACE-REVERSE")

    def test_kernel_cannot_import_technical_adapter(self) -> None:
        violations = self.analyze(
            "import fastapi\n",
            module="armi_kernel.application.example",
            distribution="armi-kernel",
        )
        self.assert_rejected(violations, "ARC-SURFACE-KERNEL-TECH")

    def test_cross_distribution_deep_import_is_rejected(self) -> None:
        violations = self.analyze(
            "from armi_kernel.contracts.ids import SubjectId\n",
            module="armi_admin.application.example",
            distribution="armi-admin",
        )
        self.assert_rejected(violations, "ARC-SURFACE-DEEP")

    def test_private_cross_distribution_name_is_rejected(self) -> None:
        violations = self.analyze(
            "from armi_kernel.contracts import _InternalContract\n",
            module="armi_runtime.interfaces.example",
            distribution="armi-runtime",
        )
        self.assert_rejected(violations, "ARC-SURFACE-INTERNAL")

    def test_unexported_cross_distribution_name_is_rejected(self) -> None:
        violations = self.analyze(
            "from armi_kernel.contracts import RepositoryRow\n",
            module="armi_runtime.interfaces.example",
            distribution="armi-runtime",
        )
        self.assert_rejected(violations, "ARC-SURFACE-EXPORT")

    def test_dynamic_public_surface_is_rejected(self) -> None:
        violations = self.analyze(
            "__all__ = tuple()\n",
            module="armi_kernel.contracts",
            distribution="armi-kernel",
            is_package=True,
        )
        self.assert_rejected(violations, "ARC-SURFACE-EXPORT")

    def test_star_import_is_rejected(self) -> None:
        violations = self.analyze(
            "from armi_kernel.contracts import *\n",
            module="armi_runtime.interfaces.example",
            distribution="armi-runtime",
        )
        self.assert_rejected(violations, "ARC-SURFACE-STAR")

    def test_domain_cannot_depend_on_application(self) -> None:
        violations = self.analyze(
            "from armi_kernel.application import PublicPort\n",
            module="armi_kernel.domain.example",
            distribution="armi-kernel",
        )
        self.assert_rejected(violations, "ARC-SURFACE-REVERSE")

    def test_runtime_layers_cannot_depend_on_composition(self) -> None:
        violations = self.analyze(
            "from armi_runtime.composition import build\n",
            module="armi_runtime.interfaces.example",
            distribution="armi-runtime",
        )
        self.assert_rejected(violations, "ARC-SURFACE-REVERSE")


if __name__ == "__main__":
    unittest.main()
