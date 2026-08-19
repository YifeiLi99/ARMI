from types import SimpleNamespace

import pytest
from armi_live_vision.api import CameraDevice, CameraFormat, LiveVisionViolation
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


@pytest.mark.asyncio
async def test_open_uses_only_exact_directshow_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = CameraDevice("first", "path-1", "loc-1")
    exact = CameraDevice("exact", "path-2", "loc-2")
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
        DirectShowUsbCamera, "devices", staticmethod(lambda: (first, exact))
    )

    await DirectShowUsbCamera().open(exact, CameraFormat())

    assert calls == [(1, 700)]


@pytest.mark.asyncio
async def test_missing_exact_device_never_opens_default_camera(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exact = CameraDevice("exact", "path-2", "loc-2")
    monkeypatch.setattr(DirectShowUsbCamera, "devices", staticmethod(tuple))

    with pytest.raises(LiveVisionViolation) as raised:
        await DirectShowUsbCamera().open(exact, CameraFormat())

    assert raised.value.code == "VISION-DEVICE-UNAVAILABLE"
