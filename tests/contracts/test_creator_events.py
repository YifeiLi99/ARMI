"""CON-SSE checks for the technology-neutral invalidation contract."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime
from typing import cast
from uuid import uuid7

from armi_kernel.application import (
    CreatorEventResourceKind,
    CreatorEventViolation,
    CreatorProjectionInvalidation,
)
from armi_kernel.contracts import Instant


class CreatorEventContractTests(unittest.TestCase):
    def test_scene_timeline_invalidation_is_frozen(self) -> None:
        invalidation = CreatorProjectionInvalidation(
            resource_kind=CreatorEventResourceKind.SCENE_TIMELINE,
            resource_ref="default",
            occurred_at=Instant(datetime(2026, 7, 30, tzinfo=UTC)),
            projection_version="scene-timeline.v3",
        )
        self.assertEqual(invalidation.resource_kind.value, "scene_timeline")
        self.assertEqual(invalidation.resource_ref, "default")
        self.assertEqual(invalidation.projection_version, "scene-timeline.v3")

    def test_projection_and_resource_are_strict(self) -> None:
        instant = Instant(datetime(2026, 7, 30, tzinfo=UTC))
        with self.assertRaisesRegex(
            CreatorEventViolation,
            "CON-SSE-RESOURCE",
        ):
            CreatorProjectionInvalidation(
                resource_kind=cast(CreatorEventResourceKind, "scene_timeline"),
                resource_ref="default",
                occurred_at=instant,
                projection_version="scene-timeline.v3",
            )
        with self.assertRaisesRegex(
            CreatorEventViolation,
            "CON-SSE-PROJECTION",
        ):
            CreatorProjectionInvalidation(
                resource_kind=CreatorEventResourceKind.SCENE_TIMELINE,
                resource_ref="default",
                occurred_at=instant,
                projection_version="scene-timeline.v1",
            )

    def test_activity_invalidation_uses_activity_identity(self) -> None:
        activity_id = uuid7()
        invalidation = CreatorProjectionInvalidation(
            resource_kind=CreatorEventResourceKind.ACTIVITY,
            resource_ref=str(activity_id),
            occurred_at=Instant(datetime(2026, 8, 4, tzinfo=UTC)),
            projection_version="creator-activity.v1",
        )
        self.assertEqual(invalidation.resource_ref, str(activity_id))


if __name__ == "__main__":
    unittest.main()
