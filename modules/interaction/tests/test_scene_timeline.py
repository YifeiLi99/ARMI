from __future__ import annotations

import base64
import hashlib
import hmac
import unittest
from datetime import UTC, datetime
from uuid import uuid7

import rfc8785
from armi_interaction._timeline_postgresql import SceneTimelineCursorCodec
from armi_interaction.api import (
    CreatorSceneCollection,
    CreatorSceneCreateCommand,
    CreatorSceneStatusCommand,
    CreatorSceneView,
    SceneKey,
    SceneQueryViolation,
    SceneStatus,
    SceneTimelineItem,
    SceneTimelinePage,
    SceneTimelineQuery,
    TimelineItemId,
)
from armi_kernel.application import (
    AuditResultStatus,
)
from armi_kernel.contracts import Instant, TraceId


class SceneTimelineContractTests(unittest.TestCase):
    def test_empty_page_and_ordered_items_are_strict(self) -> None:
        key = SceneKey("default")
        self.assertEqual(SceneTimelinePage(scene_key=key, items=()).items, ())
        occurred = Instant(datetime(2026, 7, 30, 10, tzinfo=UTC))
        older = SceneTimelineItem(
            TimelineItemId(uuid7()),
            "creator.input",
            uuid7(),
            AuditResultStatus.ACCEPTED,
            occurred,
        )
        newer = SceneTimelineItem(
            TimelineItemId(uuid7()),
            "runtime.response",
            uuid7(),
            AuditResultStatus.COMPLETED,
            occurred,
        )
        ordered = tuple(
            sorted(
                (older, newer),
                key=lambda item: (
                    item.occurred_at.value,
                    item.timeline_item_id.value.bytes,
                ),
            )
        )
        self.assertEqual(SceneTimelinePage(key, ordered).items, ordered)
        with self.assertRaises(SceneQueryViolation):
            SceneTimelinePage(key, tuple(reversed(ordered)))

    def test_scene_key_and_limit_boundaries(self) -> None:
        for value in ("default", "creator.dialogue-1", "a" * 64):
            with self.subTest(value=value):
                self.assertEqual(SceneKey(value).value, value)
        for value in ("", "Default", "a" * 65, "with space"):
            with self.subTest(value=value), self.assertRaises(SceneQueryViolation):
                SceneKey(value)
        for limit in (1, 100):
            SceneTimelineQuery(SceneKey("default"), limit)
        for limit in (0, 101, True):
            with self.subTest(limit=limit), self.assertRaises(SceneQueryViolation):
                SceneTimelineQuery(SceneKey("default"), limit)

    def test_named_scene_lifecycle_contract_preserves_default_anchor(self) -> None:
        opened = Instant(datetime(2026, 8, 6, 10, tzinfo=UTC))
        default = CreatorSceneView(
            uuid7(),
            SceneKey("default"),
            SceneStatus.OPEN,
            opened,
            None,
            None,
            True,
        )
        named = CreatorSceneView(
            uuid7(),
            SceneKey("night-talk"),
            SceneStatus.CLOSED,
            opened,
            Instant(datetime(2026, 8, 6, 11, tzinfo=UTC)),
            uuid7(),
            False,
        )
        self.assertEqual(
            CreatorSceneCollection((default, named)).scenes,
            (default, named),
        )
        trace = TraceId("a" * 32)
        CreatorSceneCreateCommand(SceneKey("night-talk"), trace)
        CreatorSceneStatusCommand(SceneKey("night-talk"), SceneStatus.OPEN, trace)
        with self.assertRaises(SceneQueryViolation):
            CreatorSceneStatusCommand(SceneKey("default"), SceneStatus.CLOSED, trace)

    def test_creator_input_requires_a_public_operation_reference(self) -> None:
        occurred = Instant(datetime(2026, 7, 30, 10, tzinfo=UTC))
        operation_ref = uuid7()
        item = SceneTimelineItem(
            TimelineItemId(uuid7()),
            "creator_input",
            uuid7(),
            AuditResultStatus.ACCEPTED,
            occurred,
            operation_ref,
            message="原始输入",
        )
        self.assertEqual(item.operation_ref, operation_ref)
        self.assertEqual(item.message, "原始输入")
        with self.assertRaises(SceneQueryViolation) as missing:
            SceneTimelineItem(
                TimelineItemId(uuid7()),
                "creator_input",
                uuid7(),
                AuditResultStatus.ACCEPTED,
                occurred,
            )
        self.assertEqual(missing.exception.code, "CON-SCENE-OPERATION")
        with self.assertRaises(SceneQueryViolation) as missing_message:
            SceneTimelineItem(
                TimelineItemId(uuid7()),
                "creator_input",
                uuid7(),
                AuditResultStatus.ACCEPTED,
                occurred,
                operation_ref,
            )
        self.assertEqual(missing_message.exception.code, "CON-SCENE-MESSAGE")

    def test_creator_response_requires_effect_or_verified_voice_text(self) -> None:
        occurred = Instant(datetime(2026, 7, 30, 10, tzinfo=UTC))
        effect_ref = uuid7()
        item = SceneTimelineItem(
            TimelineItemId(uuid7()),
            "creator_response",
            effect_ref,
            AuditResultStatus.COMPLETED,
            occurred,
            effect_ref=effect_ref,
        )
        self.assertEqual(item.effect_ref, effect_ref)
        voice = SceneTimelineItem(
            TimelineItemId(uuid7()),
            "creator_response",
            uuid7(),
            AuditResultStatus.COMPLETED,
            occurred,
            message="已经真实播放",
            modality="live_voice",
        )
        self.assertIsNone(voice.effect_ref)
        self.assertEqual(voice.message, "已经真实播放")
        with self.assertRaises(SceneQueryViolation) as missing:
            SceneTimelineItem(
                TimelineItemId(uuid7()),
                "creator_response",
                effect_ref,
                AuditResultStatus.COMPLETED,
                occurred,
            )
        self.assertEqual(missing.exception.code, "CON-SCENE-EFFECT")

    def test_cursor_is_deterministic_scoped_and_tamper_evident(self) -> None:
        environment_id = uuid7()
        creator_party_id = uuid7()
        scene_id = uuid7()
        boundary_id = uuid7()
        boundary_at = Instant(datetime(2026, 7, 30, 10, tzinfo=UTC))
        codec = SceneTimelineCursorCodec(
            key=b"k" * 32,
            environment_id=environment_id,
            creator_party_id=creator_party_id,
        )
        cursor = codec.encode(
            scene_id=scene_id,
            scene_key="default",
            limit=50,
            before_at=boundary_at,
            before_id=boundary_id,
        )
        self.assertEqual(
            cursor,
            codec.encode(
                scene_id=scene_id,
                scene_key="default",
                limit=50,
                before_at=boundary_at,
                before_id=boundary_id,
            ),
        )
        self.assertEqual(
            codec.decode(
                cursor,
                scene_id=scene_id,
                scene_key="default",
                limit=50,
            ),
            (boundary_at, boundary_id),
        )
        with self.assertRaises(SceneQueryViolation) as wrong_limit:
            codec.decode(
                cursor,
                scene_id=scene_id,
                scene_key="default",
                limit=49,
            )
        self.assertEqual(wrong_limit.exception.code, "SCENE-CURSOR-INVALID")
        prefix, payload, signature = cursor.value.split(".")
        replacement = "A" if signature[0] != "A" else "B"
        tampered = type(cursor)(f"{prefix}.{payload}.{replacement}{signature[1:]}")
        with self.assertRaises(SceneQueryViolation):
            codec.decode(
                tampered,
                scene_id=scene_id,
                scene_key="default",
                limit=50,
            )
        rotated = SceneTimelineCursorCodec(
            key=b"r" * 32,
            environment_id=environment_id,
            creator_party_id=creator_party_id,
        )
        with self.assertRaises(SceneQueryViolation):
            rotated.decode(
                cursor,
                scene_id=scene_id,
                scene_key="default",
                limit=50,
            )
        stale_payload = {
            "contract_version": "1.0",
            "projection_version": "scene-timeline.v1",
            "environment_id": str(environment_id),
            "creator_party_id": str(creator_party_id),
            "scene_id": str(scene_id),
            "scene_key": "default",
            "limit": 50,
            "direction": "older",
            "before_at": boundary_at.to_wire(),
            "before_id": str(boundary_id),
        }
        encoded = base64.urlsafe_b64encode(rfc8785.dumps(stale_payload)).rstrip(b"=")
        signature = base64.urlsafe_b64encode(
            hmac.new(b"k" * 32, encoded, hashlib.sha256).digest()
        ).rstrip(b"=")
        stale = type(cursor)(
            f"v1.{encoded.decode('ascii')}.{signature.decode('ascii')}"
        )
        with self.assertRaises(SceneQueryViolation) as stale_error:
            codec.decode(
                stale,
                scene_id=scene_id,
                scene_key="default",
                limit=50,
            )
        self.assertEqual(stale_error.exception.code, "SCENE-CURSOR-STALE")


if __name__ == "__main__":
    unittest.main()
