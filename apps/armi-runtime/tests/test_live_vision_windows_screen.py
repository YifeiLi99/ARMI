import asyncio
from io import BytesIO

import pytest
from armi_live_vision.api import (
    LiveVisionViolation,
    ScreenSourceIdentity,
    VisualCaptureFormat,
)
from armi_runtime.adapters.vision import windows_screen
from armi_runtime.adapters.vision.windows_screen import WindowsScreenSource
from PIL import Image

IDENTITY = ScreenSourceIdentity(
    r"\\.\DISPLAY1",
    r"\\?\DISPLAY#HKC2701#exact",
    "HKC 2701",
    1920,
    1080,
)
DISPLAY = windows_screen._Display(IDENTITY, (10, 20, 1930, 1100))


def test_open_requires_exact_display_identity_and_dimensions(monkeypatch) -> None:
    monkeypatch.setattr(windows_screen, "_enumerate_displays", lambda: (DISPLAY,))
    monkeypatch.setattr(windows_screen, "_interactive_desktop_available", lambda: True)

    async def scenario() -> None:
        source = WindowsScreenSource()
        await source.open(IDENTITY, VisualCaptureFormat(1920, 1080, 1))
        with pytest.raises(LiveVisionViolation) as mismatch:
            await source.open(IDENTITY, VisualCaptureFormat(1280, 720, 1))
        assert mismatch.value.code == "VISION-SCREEN-IDENTITY-MISMATCH"

    asyncio.run(scenario())


def test_open_rejects_locked_or_noninteractive_desktop(monkeypatch) -> None:
    monkeypatch.setattr(windows_screen, "_enumerate_displays", lambda: (DISPLAY,))
    monkeypatch.setattr(windows_screen, "_interactive_desktop_available", lambda: False)

    async def scenario() -> None:
        with pytest.raises(LiveVisionViolation) as unavailable:
            await WindowsScreenSource().open(
                IDENTITY, VisualCaptureFormat(1920, 1080, 1)
            )
        assert unavailable.value.code == "VISION-DESKTOP-UNAVAILABLE"

    asyncio.run(scenario())


def test_capture_uses_exact_bounds_and_builds_bounded_preview(monkeypatch) -> None:
    monkeypatch.setattr(windows_screen, "_enumerate_displays", lambda: (DISPLAY,))
    monkeypatch.setattr(windows_screen, "_interactive_desktop_available", lambda: True)
    captured: list[tuple[tuple[int, int, int, int], bool]] = []

    def grab(*, bbox, all_screens):
        captured.append((bbox, all_screens))
        return Image.new("RGB", (1920, 1080), "navy")

    monkeypatch.setattr(windows_screen.ImageGrab, "grab", grab)

    async def scenario() -> None:
        source = WindowsScreenSource()
        await source.open(IDENTITY, VisualCaptureFormat(1920, 1080, 1))
        frame = await source.next_frame()
        assert captured == [((10, 20, 1930, 1100), True)]
        assert (frame.width, frame.height) == (1920, 1080)
        assert len(frame.grayscale_thumbnail) == 160 * 90
        assert frame.preview_jpeg is not None
        with Image.open(BytesIO(frame.preview_jpeg)) as preview:
            assert max(preview.size) == 640

    asyncio.run(scenario())


def test_capture_rejects_identity_change_without_fallback(monkeypatch) -> None:
    values = iter(((DISPLAY,), ()))
    monkeypatch.setattr(windows_screen, "_enumerate_displays", lambda: next(values))
    monkeypatch.setattr(windows_screen, "_interactive_desktop_available", lambda: True)

    async def scenario() -> None:
        source = WindowsScreenSource()
        await source.open(IDENTITY, VisualCaptureFormat(1920, 1080, 1))
        with pytest.raises(LiveVisionViolation) as mismatch:
            await source.next_frame()
        assert mismatch.value.code == "VISION-SCREEN-IDENTITY-MISMATCH"

    asyncio.run(scenario())
