from types import SimpleNamespace

import pytest
from armi_live_vision.api import (
    CameraSourceIdentity,
    LiveVisionViolation,
    VisualCaptureFormat,
)
from armi_runtime.adapters.vision import directshow
from armi_runtime.adapters.vision.directshow import DirectShowUsbCamera


class _Capture:
    def __init__(self, index: int, backend: int) -> None:
        self.index = index
        self.backend = backend
        self.values = {3: 1280.0, 4: 720.0, 42: float(backend)}
        self.released = False

    def set(self, key: int, value: float) -> bool:
        self.values[key] = value
        return True

    def get(self, key: int) -> float:
        return self.values[key]

    def isOpened(self) -> bool:
        return True

    def release(self) -> None:
        self.released = True


def test_sources_keep_exact_usb_location_and_remove_duplicates(monkeypatch) -> None:
    path = r"\\?\usb#vid_03f0&pid_e207&mi_00#6&exact&0&0000"
    missing_location = r"\\?\usb#vid_0000&pid_0000#missing"
    monkeypatch.setattr(
        directshow,
        "_directshow_monikers",
        lambda: (
            ("HP 320 FHD Webcam", path),
            ("HP 320 FHD Webcam", path),
            ("Unknown", missing_location),
        ),
    )
    monkeypatch.setattr(
        directshow,
        "_location_paths",
        lambda instance: (
            (r"PCIROOT(0)#PCI(1400)#USBROOT(0)#USB(4)#USB(4)#USB(3)#USBMI(0)",)
            if "03F0" in instance
            else ()
        ),
    )

    assert DirectShowUsbCamera.sources() == (
        CameraSourceIdentity(
            "HP 320 FHD Webcam",
            path,
            r"PCIROOT(0)#PCI(1400)#USBROOT(0)#USB(4)#USB(4)#USB(3)#USBMI(0)",
        ),
    )


def test_empty_video_category_returns_no_source(monkeypatch) -> None:
    monkeypatch.setattr(directshow, "_directshow_monikers", tuple)
    assert DirectShowUsbCamera.sources() == ()


@pytest.mark.asyncio
async def test_open_uses_only_exact_directshow_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = CameraSourceIdentity("first", "path-1", "loc-1")
    exact = CameraSourceIdentity("exact", "path-2", "loc-2")
    calls: list[tuple[int, int]] = []

    def create(index: int, backend: int) -> _Capture:
        calls.append((index, backend))
        return _Capture(index, backend)

    fake_cv2 = SimpleNamespace(
        CAP_DSHOW=700,
        CAP_PROP_FRAME_WIDTH=3,
        CAP_PROP_FRAME_HEIGHT=4,
        CAP_PROP_FPS=5,
        CAP_PROP_BACKEND=42,
        VideoCapture=create,
    )
    monkeypatch.setitem(__import__("sys").modules, "cv2", fake_cv2)
    monkeypatch.setattr(
        DirectShowUsbCamera, "sources", staticmethod(lambda: (first, exact))
    )

    await DirectShowUsbCamera().open(exact, VisualCaptureFormat())

    assert calls == [(1, 700)]


@pytest.mark.asyncio
async def test_missing_exact_device_never_opens_default_camera(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exact = CameraSourceIdentity("exact", "path-2", "loc-2")
    monkeypatch.setattr(DirectShowUsbCamera, "sources", staticmethod(tuple))

    with pytest.raises(LiveVisionViolation) as raised:
        await DirectShowUsbCamera().open(exact, VisualCaptureFormat())

    assert raised.value.code == "VISION-DEVICE-UNAVAILABLE"
