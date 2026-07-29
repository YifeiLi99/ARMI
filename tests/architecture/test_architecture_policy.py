"""Negative and positive tests for owner and evolution policy gates."""

from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

from tools.check_architecture_policy import analyze_source, check_repository

BASE_POLICY: dict[str, Any] = {
    "schema_version": "armi.architecture-policy.v1",
    "persistence_markers": ["persistence", "repositories", "repository"],
    "database_driver_roots": ["psycopg", "psycopg_pool"],
    "database_driver_boundaries": [],
    "write_surfaces": [],
    "write_surfaces_not_applicable_reason": "not implemented",
    "named_coordinators": [],
    "named_coordinators_not_applicable_reason": "not implemented",
    "transaction_control_exemptions": [],
    "transaction_control_exemptions_not_applicable_reason": "not implemented",
    "coordinator_forbidden_io_roots": ["openai", "playwright", "mcp", "httpx"],
    "forbidden_entry_points": [],
    "forbidden_entry_points_not_applicable_reason": "greenfield",
}


class ArchitecturePolicyTests(unittest.TestCase):
    def codes(
        self,
        source: str,
        *,
        module: str = "armi_runtime.adapters.example",
        policy: dict[str, Any] | None = None,
    ) -> set[str]:
        selected_policy = policy if policy is not None else BASE_POLICY
        return {
            item.code
            for item in analyze_source(
                source,
                module=module,
                path="<architecture-policy-sample>",
                policy=selected_policy,
            )
        }

    def test_current_repository_satisfies_policy(self) -> None:
        self.assertEqual(check_repository(Path.cwd()), [])

    def test_unregistered_persistence_is_rejected(self) -> None:
        codes = self.codes(
            "class SubjectRepository:\n    pass\n",
            module="armi_runtime.adapters.persistence.subject_repository",
        )
        self.assertIn("ARC-OWNER-UNREGISTERED-WRITE-SURFACE", codes)

    def test_direct_database_driver_is_rejected(self) -> None:
        self.assertIn("ARC-OWNER-DIRECT-DRIVER", self.codes("import psycopg\n"))

    def test_cross_owner_write_reference_is_rejected(self) -> None:
        policy = {
            **BASE_POLICY,
            "write_surfaces": [
                {
                    "id": "subject-write",
                    "module": "armi_runtime.adapters.persistence.subject_repository",
                    "owner": "subject",
                    "allowed_callers": ["armi_kernel.application.subject"],
                }
            ],
            "write_surfaces_not_applicable_reason": "",
        }
        codes = self.codes(
            "from armi_runtime.adapters.persistence import subject_repository\n",
            module="armi_kernel.application.memory",
            policy=policy,
        )
        self.assertIn("ARC-OWNER-CROSS-WRITE", codes)

    def test_repository_cannot_control_transaction(self) -> None:
        codes = self.codes(
            "def save(connection):\n    connection.commit()\n",
            module="armi_runtime.adapters.persistence.subject_repository",
        )
        self.assertIn("ARC-OWNER-TRANSACTION-CONTROL", codes)

    def test_registered_coordinator_can_control_transaction(self) -> None:
        module = "armi_runtime.adapters.persistence.unit_of_work"
        policy = {
            **BASE_POLICY,
            "named_coordinators": [
                {
                    "id": "runtime-uow",
                    "module": module,
                    "owner": "transaction-coordination",
                    "allowed_write_surfaces": [],
                }
            ],
            "named_coordinators_not_applicable_reason": "",
        }
        self.assertNotIn(
            "ARC-OWNER-TRANSACTION-CONTROL",
            self.codes(
                "def finish(connection):\n    connection.commit()\n",
                module=module,
                policy=policy,
            ),
        )

    def test_coordinator_cannot_import_slow_external_io(self) -> None:
        module = "armi_runtime.adapters.persistence.unit_of_work"
        policy = {
            **BASE_POLICY,
            "named_coordinators": [
                {
                    "id": "runtime-uow",
                    "module": module,
                    "owner": "transaction-coordination",
                    "allowed_write_surfaces": [],
                }
            ],
            "named_coordinators_not_applicable_reason": "",
        }
        self.assertIn(
            "ARC-OWNER-COORDINATOR-IO",
            self.codes("import openai\n", module=module, policy=policy),
        )

    def test_global_service_locator_is_rejected(self) -> None:
        self.assertIn(
            "ARC-BINDING-GLOBAL-LOCATOR",
            self.codes("service_registry = {}\n"),
        )

    def test_dynamic_implementation_discovery_is_rejected(self) -> None:
        self.assertIn(
            "ARC-BINDING-DISCOVERY",
            self.codes(
                "import importlib.metadata\n"
                "implementations = importlib.metadata.entry_points()\n"
            ),
        )

    def test_forbidden_old_entry_is_rejected(self) -> None:
        policy = {
            **BASE_POLICY,
            "forbidden_entry_points": [
                {"id": "old-runtime", "module": "armi_runtime.old_entry"}
            ],
            "forbidden_entry_points_not_applicable_reason": "",
        }
        self.assertIn(
            "EVO-CLEAN-OLD-ENTRY",
            self.codes("import armi_runtime.old_entry\n", policy=policy),
        )


if __name__ == "__main__":
    unittest.main()
