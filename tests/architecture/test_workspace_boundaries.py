"""Negative and positive tests for the M0 package boundaries."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tools.check_workspace_boundaries import (
    analyze_source,
    check_repository,
    exit_code_for,
)
from tools.schema_ownership import (
    TABLE_OWNERSHIP,
    ownership_registry_errors,
    scan_repository_foreign_table_accesses,
    scan_source_foreign_table_accesses,
    schema_tables_at_head,
)

ROOT = Path(__file__).resolve().parents[2]
PUBLIC_EXPORTS = {
    "armi_evidence.api": frozenset({"EvidenceId", "EvidenceWritePort"}),
    "armi_evidence.bootstrap": frozenset({"bootstrap_evidence"}),
    "armi_kernel": frozenset(),
    "armi_kernel.application": frozenset(
        {
            "ArtifactId",
            "ArtifactIntegrityStatus",
            "ArtifactPolicy",
            "ArtifactPort",
            "ArtifactPrivacyScope",
            "ArtifactRef",
            "ArtifactViolation",
            "AuditDraft",
            "AuditEventId",
            "AuditQuery",
            "AuditQueryResult",
            "AuditRecord",
            "AuditReference",
            "AuditResultStatus",
            "AuditSensitivity",
            "AuditViolation",
            "AuditWriter",
            "CredentialLocator",
            "CredentialPort",
            "CredentialPurpose",
            "DurableWorkPort",
            "DurableWorkWriter",
            "BeforeCommitHook",
            "BirthManifest",
            "BirthPort",
            "BirthResult",
            "BirthViolation",
            "CasStatus",
            "PostCommitAction",
            "PersonalityAnchor",
            "PublishedArtifact",
            "RuntimeAuthorityPort",
            "RuntimeAuthorityRecord",
            "RuntimeAuthorityStatus",
            "RuntimeAuthorityViolation",
            "RuntimeFence",
            "RuntimeInstanceId",
            "SecretHandle",
            "StagedArtifact",
            "TransactionIsolation",
            "UnitOfWork",
            "VerifiedByteStream",
            "WorkAttemptId",
            "WorkDraft",
            "WorkId",
            "WorkLease",
            "WorkOwner",
            "WorkPayloadRef",
            "WorkRecord",
            "WorkResultRef",
            "WorkStatus",
            "WorkViolation",
            "classify_cas_rows",
        }
    ),
    "armi_kernel.contracts": frozenset(
        {
            "CONTRACT_VERSION",
            "ContractViolation",
            "SubjectId",
        }
    ),
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

    def test_schema_owner_registry_matches_effective_head(self) -> None:
        schema_root = (
            ROOT
            / "apps/armi-runtime/src/armi_runtime/composition/runtime_resources/schema"
        )
        self.assertEqual(ownership_registry_errors(schema_root), ())
        self.assertEqual(schema_tables_at_head(schema_root), frozenset(TABLE_OWNERSHIP))
        self.assertNotIn("action_operations", TABLE_OWNERSHIP)

    def test_schema_owner_registry_rejects_unregistered_and_stale_tables(self) -> None:
        with TemporaryDirectory() as directory:
            schema_root = Path(directory)
            baseline = schema_root / "baseline"
            revisions = schema_root / "alembic" / "versions"
            baseline.mkdir(parents=True)
            revisions.mkdir(parents=True)
            baseline.joinpath("10_test.sql").write_text(
                "CREATE TABLE armi.unregistered_fact (id uuid);\n",
                encoding="utf-8",
            )
            errors = ownership_registry_errors(schema_root)
        self.assertIn("unregistered table: armi.unregistered_fact", errors)
        self.assertIn("stale registry table: armi.subjects", errors)

    def test_final_owner_sql_boundary_is_zero_tolerance(self) -> None:
        accesses = scan_repository_foreign_table_accesses(ROOT)
        production = tuple(
            item
            for item in accesses
            if "/runtime_resources/schema/baseline/" not in item.path
            and "/runtime_resources/schema/alembic/versions/" not in item.path
        )
        self.assertEqual(len(accesses), 0)
        self.assertEqual(len(production), 0)
        self.assertFalse(
            tuple(
                item
                for item in production
                if item.source_owner == "data-rights"
                or item.table_owner == "data-rights"
            )
        )

    def test_sql_owner_scanner_finds_reads_writes_and_ctes(self) -> None:
        accesses = scan_source_foreign_table_accesses(
            '''
READ = "SELECT * FROM armi.opportunities"
WRITE = "INSERT INTO armi.effects (effect_id) VALUES (%s)"
CTE = """WITH chosen AS (
    SELECT opportunity_id FROM armi.opportunities
) DELETE FROM armi.effects WHERE effect_id IN (SELECT * FROM chosen)"""
OWN = "UPDATE armi.cognitive_episodes SET status = 'done'"
''',
            path="modules/cognition/src/armi_cognition/example.py",
            source_owner="cognition",
        )
        self.assertEqual(
            [(value.operation, value.table, value.table_owner) for value in accesses],
            [
                ("FROM", "opportunities", "attention"),
                ("INSERT INTO", "effects", "effect"),
                ("FROM", "opportunities", "attention"),
                ("DELETE FROM", "effects", "effect"),
            ],
        )

    def test_startup_recovery_sql_stays_with_each_table_owner(self) -> None:
        sources = {
            "runtime": ROOT
            / "apps/armi-runtime/src/armi_runtime/adapters/persistence/recovery.py",
            **{
                owner: ROOT
                / "modules"
                / distribution
                / "src"
                / package
                / "_recovery.py"
                for owner, distribution, package in (
                    ("capability", "capability", "armi_capability"),
                    ("codex", "codex", "armi_codex"),
                    ("cognition", "cognition", "armi_cognition"),
                    ("effect", "effect", "armi_effect"),
                    ("evidence", "evidence", "armi_evidence"),
                    ("expression", "expression", "armi_expression"),
                    ("interaction", "interaction", "armi_interaction"),
                    ("mood", "mood", "armi_mood"),
                    ("attention", "attention", "armi_attention"),
                    ("perception", "perception", "armi_perception"),
                    ("prompt", "prompt", "armi_prompt"),
                    ("subject-state", "subject-state", "armi_subject_state"),
                    (
                        "web-observation",
                        "web-observation",
                        "armi_web_observation",
                    ),
                )
            },
        }
        accesses = tuple(
            access
            for owner, path in sources.items()
            for access in scan_source_foreign_table_accesses(
                path.read_text(encoding="utf-8"),
                path=path.relative_to(ROOT).as_posix(),
                source_owner=owner,
            )
        )

        self.assertEqual(accesses, ())
        self.assertFalse(
            (
                ROOT
                / "apps/armi-runtime/src/armi_runtime/adapters/persistence/recovery_responsibilities.py"
            ).exists()
        )

    def test_internal_policies_are_code_contracts_not_governance_json(self) -> None:
        resources = (
            ROOT / "apps/armi-runtime/src/armi_runtime/composition/runtime_resources"
        )
        self.assertFalse((resources / "context-policy.manifest.json").exists())
        self.assertFalse(
            (resources / "candidate-validation-policy.manifest.json").exists()
        )

    def test_explicit_kernel_application_export_is_allowed(self) -> None:
        violations = self.analyze(
            "from armi_kernel.application import CredentialPort\n",
            module="armi_runtime.adapters.example",
            distribution="armi-runtime",
        )
        self.assertEqual(violations, [])
        self.assertEqual(exit_code_for(violations), 0)

    def test_explicit_kernel_contract_export_is_allowed(self) -> None:
        violations = self.analyze(
            "from armi_kernel.contracts import SubjectId\n",
            module="armi_runtime.interfaces.example",
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

    def test_evidence_public_contract_is_available_to_business_modules(self) -> None:
        violations = self.analyze(
            "from armi_evidence.api import EvidenceId\n",
            module="armi_interaction.api",
            distribution="armi-interaction",
        )
        self.assertEqual(violations, [])

    def test_evidence_cannot_depend_on_runtime(self) -> None:
        violations = self.analyze(
            "from armi_runtime.composition import database\n",
            module="armi_evidence.api",
            distribution="armi-evidence",
        )
        self.assert_rejected(violations, "ARC-SURFACE-REVERSE")

    def test_evidence_bootstrap_is_reserved_for_composition(self) -> None:
        violations = self.analyze(
            "from armi_evidence.bootstrap import bootstrap_evidence\n",
            module="armi_runtime.adapters.example",
            distribution="armi-runtime",
        )
        self.assert_rejected(violations, "ARC-SURFACE-BOOTSTRAP")

    def test_kernel_cannot_import_technical_adapter(self) -> None:
        violations = self.analyze(
            "import fastapi\n",
            module="armi_kernel.application.example",
            distribution="armi-kernel",
        )
        self.assert_rejected(violations, "ARC-SURFACE-KERNEL-TECH")

    def test_napcat_channel_cannot_import_armi(self) -> None:
        violations = self.analyze(
            "from armi_interaction.api import ExternalMessageInputPort\n",
            module="armi_channel_napcat.example",
            distribution="armi-channel-napcat",
        )
        self.assert_rejected(violations, "ARC-SURFACE-REVERSE")

    def test_qq_adapter_cannot_import_runtime(self) -> None:
        violations = self.analyze(
            "from armi_runtime.composition import build\n",
            module="armi_adapter_qq.example",
            distribution="armi-adapter-qq",
        )
        self.assert_rejected(violations, "ARC-SURFACE-REVERSE")

    def test_kernel_contract_cannot_import_validation_or_digest_library(self) -> None:
        for package in ("pydantic", "rfc8785", "psycopg"):
            with self.subTest(package=package):
                violations = self.analyze(
                    f"import {package}\n",
                    module="armi_kernel.contracts.example",
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

    def test_public_api_any_is_rejected(self) -> None:
        violations = self.analyze(
            "from typing import Any\nclass Port:\n    value: Any\n",
            module="armi_evidence.api",
            distribution="armi-evidence",
        )
        self.assert_rejected(violations, "ARC-PUBLIC-ANY")

    def test_business_package_root_reexport_is_rejected(self) -> None:
        violations = self.analyze(
            "from ._private import Repository\n__all__ = ('Repository',)\n",
            module="armi_evidence",
            distribution="armi-evidence",
            is_package=True,
        )
        self.assert_rejected(violations, "ARC-PACKAGE-ROOT")

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
            "from armi_kernel.application import CredentialPort\n",
            module="armi_kernel.domain.example",
            distribution="armi-kernel",
        )
        self.assert_rejected(violations, "ARC-SURFACE-REVERSE")

    def test_kernel_application_deep_import_is_rejected(self) -> None:
        violations = self.analyze(
            "from armi_kernel.application.credentials import CredentialPort\n",
            module="armi_runtime.composition.example",
            distribution="armi-runtime",
        )
        self.assert_rejected(violations, "ARC-SURFACE-DEEP")

    def test_kernel_credential_contract_has_no_technical_or_filesystem_imports(
        self,
    ) -> None:
        source = (
            ROOT / "packages/armi-kernel/src/armi_kernel/application/credentials.py"
        ).read_text(encoding="utf-8")
        for forbidden in ("pydantic", "rfc8785", "pathlib", "os", "psycopg"):
            self.assertNotIn(f"import {forbidden}", source)

    def test_runtime_layers_cannot_depend_on_composition(self) -> None:
        violations = self.analyze(
            "from armi_runtime.composition import build\n",
            module="armi_runtime.interfaces.example",
            distribution="armi-runtime",
        )
        self.assert_rejected(violations, "ARC-SURFACE-REVERSE")


if __name__ == "__main__":
    unittest.main()
