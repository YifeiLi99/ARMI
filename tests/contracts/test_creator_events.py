"""CON-SSE checks for the technology-neutral invalidation contract."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime
from typing import cast
from uuid import uuid7

from armi_kernel.application import (
    CreatorEventViolation,
    CreatorProjectionInvalidation,
    CreatorResourceKind,
)
from armi_kernel.contracts import Instant


class CreatorEventContractTests(unittest.TestCase):
    def test_scene_timeline_invalidation_is_frozen(self) -> None:
        invalidation = CreatorProjectionInvalidation(
            resource_kind=CreatorResourceKind("scene_timeline"),
            resource_ref="default",
            occurred_at=Instant(datetime(2026, 7, 30, tzinfo=UTC)),
            projection_kind="scene-timeline",
        )
        self.assertEqual(str(invalidation.resource_kind), "scene_timeline")
        self.assertEqual(invalidation.resource_ref, "default")
        self.assertEqual(invalidation.projection_kind, "scene-timeline")

    def test_projection_and_resource_are_strict(self) -> None:
        instant = Instant(datetime(2026, 7, 30, tzinfo=UTC))
        with self.assertRaisesRegex(
            CreatorEventViolation,
            "CON-SSE-RESOURCE",
        ):
            CreatorProjectionInvalidation(
                resource_kind=cast(CreatorResourceKind, "scene_timeline"),
                resource_ref="default",
                occurred_at=instant,
                projection_kind="scene-timeline",
            )
        with self.assertRaisesRegex(
            CreatorEventViolation,
            "CON-SSE-PROJECTION",
        ):
            CreatorProjectionInvalidation(
                resource_kind=CreatorResourceKind("scene_timeline"),
                resource_ref="default",
                occurred_at=instant,
                projection_kind="INVALID",
            )

    def test_activity_invalidation_uses_activity_identity(self) -> None:
        activity_id = uuid7()
        invalidation = CreatorProjectionInvalidation(
            resource_kind=CreatorResourceKind("activity"),
            resource_ref=str(activity_id),
            occurred_at=Instant(datetime(2026, 8, 4, tzinfo=UTC)),
            projection_kind="creator-activity",
        )
        self.assertEqual(invalidation.resource_ref, str(activity_id))

    def test_maintenance_invalidation_uses_session_identity(self) -> None:
        session_id = uuid7()
        invalidation = CreatorProjectionInvalidation(
            resource_kind=CreatorResourceKind("maintenance"),
            resource_ref=str(session_id),
            occurred_at=Instant(datetime(2026, 8, 4, tzinfo=UTC)),
            projection_kind="creator-maintenance",
        )
        self.assertEqual(invalidation.resource_ref, str(session_id))

    def test_memory_invalidation_uses_memory_identity(self) -> None:
        memory_id = uuid7()
        invalidation = CreatorProjectionInvalidation(
            resource_kind=CreatorResourceKind("memory"),
            resource_ref=str(memory_id),
            occurred_at=Instant(datetime(2026, 8, 4, tzinfo=UTC)),
            projection_kind="creator-memory",
        )
        self.assertEqual(invalidation.resource_ref, str(memory_id))

    def test_relationship_invalidation_uses_relationship_identity(self) -> None:
        relationship_id = uuid7()
        invalidation = CreatorProjectionInvalidation(
            resource_kind=CreatorResourceKind("relationship"),
            resource_ref=str(relationship_id),
            occurred_at=Instant(datetime(2026, 8, 5, tzinfo=UTC)),
            projection_kind="creator-relationship",
        )
        self.assertEqual(invalidation.resource_ref, str(relationship_id))

    def test_material_invalidation_refreshes_life_record_projection(self) -> None:
        material_id = uuid7()
        invalidation = CreatorProjectionInvalidation(
            resource_kind=CreatorResourceKind("material"),
            resource_ref=str(material_id),
            occurred_at=Instant(datetime(2026, 8, 5, tzinfo=UTC)),
            projection_kind="life-record-query",
        )
        self.assertEqual(invalidation.resource_ref, str(material_id))

    def test_data_rights_invalidation_carries_only_order_identity(self) -> None:
        order_id = uuid7()
        invalidation = CreatorProjectionInvalidation(
            resource_kind=CreatorResourceKind("data_rights"),
            resource_ref=str(order_id),
            occurred_at=Instant(datetime(2026, 8, 8, tzinfo=UTC)),
            projection_kind="data-rights-order-collection",
        )
        self.assertEqual(invalidation.resource_ref, str(order_id))


if __name__ == "__main__":
    unittest.main()
