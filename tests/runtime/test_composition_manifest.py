from __future__ import annotations

import json
import unittest
from importlib.resources import files
from pathlib import Path

from armi_runtime.composition.lifecycle import RUNTIME_BLOCKING_REASONS
from armi_runtime.composition.manifest import (
    COMPOSITION_SCHEMA_VERSION,
    WEB_BINDING_ID,
    VerifiedComposition,
    verify_packaged_composition,
)
from armi_runtime.composition.runtime_errors import RuntimeViolation


class CompositionManifestTests(unittest.TestCase):
    def test_packaged_manifest_has_exact_explicit_active_bindings(self) -> None:
        verified = verify_packaged_composition()
        active = [
            (seam_id, binding)
            for seam_id, binding in verified.active_bindings
            if binding is not None
        ]

        self.assertEqual(verified.schema_version, COMPOSITION_SCHEMA_VERSION)
        self.assertEqual(len(verified.active_bindings), 10)
        self.assertEqual(
            active,
            [
                (
                    "M0-SEAM-CONTEXT",
                    "armi.context-compiler.deterministic-v1",
                ),
                (
                    "M0-SEAM-MODEL",
                    "armi.model-adapter.volcengine-ark-responses-v1",
                ),
                (
                    "M0-SEAM-COGNITIVE-CANDIDATE",
                    "armi.candidate-validator.deterministic-v1",
                ),
                (
                    "M0-SEAM-WORK-SELECTION",
                    "armi.opportunity-selector.creator-fifo-v1",
                ),
                (
                    "M0-SEAM-POLICY",
                    "armi.policy-engine.deterministic-v1",
                ),
                (
                    "M0-SEAM-EFFECT",
                    "armi.creator-response-adapter.postgresql-inbox-v1",
                ),
                (
                    "M0-SEAM-CODEX",
                    "armi.codex-runner.openai-python-sdk-v1",
                ),
                (
                    "M0-SEAM-CREATOR-PROJECTION",
                    "armi.creator-projection-workbench.v1",
                ),
                ("M0-SEAM-CREATOR-UI", "armi.creator-workbench.v1"),
            ],
        )
        self.assertEqual(verified.readiness_blockers, RUNTIME_BLOCKING_REASONS)
        self.assertIsNone(verified.active_binding_for("M0-SEAM-WEB"))
        self.assertFalse(verified.web_search_active)
        self.assertTrue(verified.digest.startswith("sha256:"))

    def test_web_activation_requires_the_exact_binding(self) -> None:
        inactive = VerifiedComposition(
            COMPOSITION_SCHEMA_VERSION,
            (("M0-SEAM-WEB", "armi.model-tool.unapproved-v1"),),
            (),
            "sha256:" + "0" * 64,
        )
        active = VerifiedComposition(
            COMPOSITION_SCHEMA_VERSION,
            (("M0-SEAM-WEB", WEB_BINDING_ID),),
            (),
            "sha256:" + "1" * 64,
        )

        self.assertFalse(inactive.web_search_active)
        self.assertTrue(active.web_search_active)
        with self.assertRaisesRegex(RuntimeViolation, "CMP-SEAM-UNKNOWN"):
            active.active_binding_for("M0-SEAM-UNKNOWN")

    def test_manifest_forbids_runtime_discovery(self) -> None:
        resource = files("armi_runtime.composition.runtime_resources").joinpath(
            "runtime-composition.manifest.json"
        )
        manifest = json.loads(resource.read_bytes())

        self.assertFalse(manifest["runtime_discovery"])
        self.assertTrue(
            all(not seam["runtime_discovery"] for seam in manifest["seams"])
        )
        self.assertTrue(manifest["runtime_business_contract"])
        self.assertNotIn("resources", manifest)

    def test_s023_selector_is_the_only_active_work_selection_binding(self) -> None:
        verified = verify_packaged_composition()
        bindings = dict(verified.active_bindings)
        self.assertEqual(
            bindings["M0-SEAM-WORK-SELECTION"],
            "armi.opportunity-selector.creator-fifo-v1",
        )
        self.assertEqual(verified.readiness_blockers, ())
        runtime_source = Path(
            "apps/armi-runtime/src/armi_runtime/composition/runtime.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("OutboxDispatcher", runtime_source)
        self.assertNotIn("PostgreSQLDurableWorkGateway", runtime_source)


if __name__ == "__main__":
    unittest.main()
