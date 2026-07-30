from __future__ import annotations

import json
import unittest
from importlib.resources import files
from pathlib import Path

from armi_runtime.composition.lifecycle import RUNTIME_BLOCKING_REASONS
from armi_runtime.composition.manifest import (
    COMPOSITION_SCHEMA_VERSION,
    verify_packaged_composition,
)


class CompositionManifestTests(unittest.TestCase):
    def test_packaged_manifest_has_exact_explicit_active_bindings(self) -> None:
        verified = verify_packaged_composition()
        active = [
            (seam_id, binding)
            for seam_id, binding in verified.active_bindings
            if binding is not None
        ]

        self.assertEqual(verified.schema_version, COMPOSITION_SCHEMA_VERSION)
        self.assertEqual(len(verified.active_bindings), 9)
        self.assertEqual(
            active,
            [
                (
                    "M0-SEAM-CREATOR-PROJECTION",
                    "armi.scene-timeline-query.v1",
                ),
                ("M0-SEAM-CREATOR-UI", "armi.creator-static.v1"),
            ],
        )
        self.assertEqual(verified.readiness_blockers, RUNTIME_BLOCKING_REASONS)
        self.assertTrue(verified.digest.startswith("sha256:"))

    def test_manifest_forbids_runtime_discovery(self) -> None:
        resource = files("armi_runtime.composition.runtime_resources").joinpath(
            "runtime-composition.manifest.json"
        )
        manifest = json.loads(resource.read_bytes())

        self.assertFalse(manifest["runtime_discovery"])
        self.assertTrue(
            all(not seam["runtime_discovery"] for seam in manifest["seams"])
        )
        self.assertFalse(manifest["runtime_business_contract"])

    def test_s014_custody_is_not_an_active_worker_binding(self) -> None:
        verified = verify_packaged_composition()
        bindings = dict(verified.active_bindings)
        self.assertIsNone(bindings["M0-SEAM-WORK-SELECTION"])
        self.assertEqual(verified.readiness_blockers, ())
        runtime_source = Path(
            "apps/armi-runtime/src/armi_runtime/composition/runtime.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("OutboxDispatcher", runtime_source)
        self.assertNotIn("PostgreSQLDurableWorkGateway", runtime_source)


if __name__ == "__main__":
    unittest.main()
