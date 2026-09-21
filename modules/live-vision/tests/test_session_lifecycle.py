import asyncio
from contextlib import asynccontextmanager
from typing import Any, cast
from unittest.mock import AsyncMock, Mock
from uuid import uuid7

import pytest
from armi_live_vision._application import DurableVisualObservationCoordinator
from armi_live_vision.api import (
    CameraSourceIdentity,
    LiveVisionViolation,
    ObservationOriginKind,
    ObservationTrigger,
    VisualSourceKind,
)


def coordinator(kind: VisualSourceKind = VisualSourceKind.CAMERA):
    result = DurableVisualObservationCoordinator(
        factory=cast(Any, Mock()),
        storage=cast(Any, Mock(prepare=AsyncMock())),
        catalog=cast(Any, Mock()),
        work=cast(Any, Mock()),
        recognizer=cast(Any, Mock()),
        prices=cast(Any, Mock()),
        evidence=cast(Any, Mock()),
        opportunity=cast(Any, Mock()),
        subject_id=uuid7(),
        source_kind=kind,
        source=CameraSourceIdentity("camera", "device", "usb"),
        width=1280,
        height=720,
        fps=5,
    )
    result.purge_expired_frames = AsyncMock(return_value=0)
    return result


def test_session_lifecycle_is_local_and_sources_are_independent():
    async def run():
        camera, screen = coordinator(), coordinator(VisualSourceKind.SCREEN)
        await camera.open_session()
        await screen.open_session()
        with pytest.raises(RuntimeError, match="VISION-SESSION-ALREADY-OPEN"):
            await camera.open_session()
        await camera.close_session()
        with pytest.raises(RuntimeError, match="session is not open"):
            await camera.observe(
                trigger=ObservationTrigger.MANUAL,
                frames=(),
                change_score=None,
                origin_kind=ObservationOriginKind.CREATOR,
            )
        assert screen._session_id is not None
        await camera.open_session()
        assert camera._session_id != screen._session_id
        cast(Any, camera._factory).unit_of_work.assert_not_called()
        cast(Any, screen._factory).unit_of_work.assert_not_called()

    asyncio.run(run())


def test_close_during_capture_dispatch_prevents_device_call():
    async def run():
        sink = coordinator()
        await sink.open_session()
        capture = AsyncMock(return_value=())
        sink.bind_capture(capture)
        unit = Mock()
        unit.work.validate_lease = AsyncMock()
        unit.work.complete = AsyncMock()
        unit.transaction.execute = AsyncMock(
            return_value=Mock(
                fetchone=AsyncMock(
                    return_value=(
                        "camera",
                        "creator",
                        "manual",
                        None,
                        None,
                        None,
                        None,
                        "key",
                    )
                )
            )
        )

        @asynccontextmanager
        async def transaction():
            yield unit
            await sink.close_session()

        cast(Any, sink._factory).unit_of_work = transaction
        record = Mock()
        record.draft.owner.reference = uuid7()
        await sink.process_claimed_capture(record)
        capture.assert_not_awaited()
        assert any(
            "VISION-SOURCE-NOT-RUNNING" in str(call)
            for call in unit.transaction.execute.call_args_list
        )

    asyncio.run(run())


def test_reopening_during_frame_publication_does_not_adopt_old_capture():
    async def run():
        sink = coordinator()
        await sink.open_session()
        session_id = sink._session_id
        assert session_id is not None

        async def publish(*args):
            await sink.close_session()
            await sink.open_session()
            return Mock()

        sink._publish = AsyncMock(side_effect=publish)
        unit = Mock()

        @asynccontextmanager
        async def transaction():
            yield unit

        cast(Any, sink._factory).unit_of_work = transaction
        with pytest.raises(LiveVisionViolation) as caught:
            await sink._attach_captured_frames(
                observation_id=uuid7(),
                session_id=session_id,
                frames=(),
                origin_kind=ObservationOriginKind.CREATOR,
                trigger=ObservationTrigger.MANUAL,
                origin_episode_id=None,
                origin_scene_id=None,
                origin_context_party_id=None,
                change_score=None,
                idempotency_key="key",
                capture_lease=cast(Any, Mock()),
            )
        assert caught.value.code == "VISION-SOURCE-NOT-RUNNING"
        unit.transaction.execute.assert_not_called()

    asyncio.run(run())
