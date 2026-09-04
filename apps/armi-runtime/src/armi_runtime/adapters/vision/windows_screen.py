"""Exact Windows display identity and in-memory screen capture."""

from __future__ import annotations

import asyncio
import ctypes
from ctypes import (
    POINTER,
    byref,
    c_bool,
    c_int,
    c_long,
    c_uint,
    c_ulong,
    c_ulonglong,
    c_ushort,
    c_void_p,
    sizeof,
)
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from typing import Any, ClassVar

from armi_live_vision.api import (
    LiveVisionViolation,
    ScreenSourceIdentity,
    VisualCaptureFormat,
    VisualFrame,
    VisualSourceIdentity,
)
from PIL import ImageGrab

QDC_ONLY_ACTIVE = 0x2
DISPLAYCONFIG_DEVICE_INFO_GET_SOURCE_NAME = 1
DISPLAYCONFIG_DEVICE_INFO_GET_TARGET_NAME = 2
ENUM_CURRENT_SETTINGS = -1
SM_REMOTESESSION = 0x1000
WTS_CURRENT_SERVER_HANDLE = 0
WTS_CURRENT_SESSION = 0xFFFFFFFF
WTS_SESSION_INFO_EX = 25


class LUID(ctypes.Structure):
    _fields_ = [("LowPart", c_ulong), ("HighPart", c_long)]


class RATIONAL(ctypes.Structure):
    _fields_ = [("Numerator", c_uint), ("Denominator", c_uint)]


class PATH_SOURCE_INFO(ctypes.Structure):
    _fields_ = [
        ("adapterId", LUID),
        ("id", c_uint),
        ("modeInfoIdx", c_uint),
        ("statusFlags", c_uint),
    ]


class PATH_TARGET_INFO(ctypes.Structure):
    _fields_ = [
        ("adapterId", LUID),
        ("id", c_uint),
        ("modeInfoIdx", c_uint),
        ("outputTechnology", c_uint),
        ("rotation", c_uint),
        ("scaling", c_uint),
        ("refreshRate", RATIONAL),
        ("scanLineOrdering", c_uint),
        ("targetAvailable", c_bool),
        ("statusFlags", c_uint),
    ]


class PATH_INFO(ctypes.Structure):
    _fields_ = [
        ("sourceInfo", PATH_SOURCE_INFO),
        ("targetInfo", PATH_TARGET_INFO),
        ("flags", c_uint),
    ]


class MODE_INFO(ctypes.Structure):
    _fields_ = [
        ("infoType", c_uint),
        ("id", c_uint),
        ("adapterId", LUID),
        ("data", ctypes.c_byte * 48),
    ]


class DEVICE_INFO_HEADER(ctypes.Structure):
    _fields_ = [("type", c_uint), ("size", c_uint), ("adapterId", LUID), ("id", c_uint)]


class SOURCE_NAME(ctypes.Structure):
    _fields_ = [
        ("header", DEVICE_INFO_HEADER),
        ("viewGdiDeviceName", ctypes.c_wchar * 32),
    ]


class TARGET_NAME(ctypes.Structure):
    _fields_ = [
        ("header", DEVICE_INFO_HEADER),
        ("flags", c_uint),
        ("outputTechnology", c_uint),
        ("edidManufactureId", c_ushort),
        ("edidProductCodeId", c_ushort),
        ("connectorInstance", c_uint),
        ("monitorFriendlyDeviceName", ctypes.c_wchar * 64),
        ("monitorDevicePath", ctypes.c_wchar * 128),
    ]


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", c_long),
        ("top", c_long),
        ("right", c_long),
        ("bottom", c_long),
    ]


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", c_ulong),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", c_ulong),
        ("szDevice", ctypes.c_wchar * 32),
    ]


class WTSINFOEX_LEVEL1_PREFIX(ctypes.Structure):
    _fields_ = [
        ("SessionId", c_ulong),
        ("SessionState", c_int),
        ("SessionFlags", c_long),
    ]


class WTSINFOEX_DATA(ctypes.Union):
    _fields_: ClassVar[list[tuple[str, Any]]] = [  # pyright: ignore[reportIncompatibleVariableOverride]
        ("level1", WTSINFOEX_LEVEL1_PREFIX),
        ("alignment", c_ulonglong),
    ]


class WTSINFOEX(ctypes.Structure):
    _fields_ = [("Level", c_ulong), ("Data", WTSINFOEX_DATA)]


@dataclass(frozen=True, slots=True)
class _Display:
    identity: ScreenSourceIdentity
    bounds: tuple[int, int, int, int]


def _monitor_bounds() -> dict[str, tuple[int, int, int, int]]:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    values: dict[str, tuple[int, int, int, int]] = {}
    callback_type = ctypes.WINFUNCTYPE(
        c_bool, c_void_p, c_void_p, POINTER(RECT), c_long
    )

    @callback_type
    def callback(monitor: int, _dc: int, _rect: Any, _data: int) -> bool:
        info = MONITORINFOEXW(cbSize=sizeof(MONITORINFOEXW))
        if user32.GetMonitorInfoW(monitor, byref(info)):
            rect = info.rcMonitor
            values[str(info.szDevice)] = (rect.left, rect.top, rect.right, rect.bottom)
        return True

    if not user32.EnumDisplayMonitors(None, None, callback, 0):
        raise ctypes.WinError(ctypes.get_last_error())
    return values


def _enumerate_displays() -> tuple[_Display, ...]:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    path_count, mode_count = c_uint(), c_uint()
    if (
        user32.GetDisplayConfigBufferSizes(
            QDC_ONLY_ACTIVE, byref(path_count), byref(mode_count)
        )
        != 0
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    paths = (PATH_INFO * path_count.value)()
    modes = (MODE_INFO * mode_count.value)()
    if (
        user32.QueryDisplayConfig(
            QDC_ONLY_ACTIVE, byref(path_count), paths, byref(mode_count), modes, None
        )
        != 0
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    bounds = _monitor_bounds()
    result: list[_Display] = []
    for path in paths[: path_count.value]:
        source = SOURCE_NAME()
        source.header = DEVICE_INFO_HEADER(
            DISPLAYCONFIG_DEVICE_INFO_GET_SOURCE_NAME,
            sizeof(SOURCE_NAME),
            path.sourceInfo.adapterId,
            path.sourceInfo.id,
        )
        target = TARGET_NAME()
        target.header = DEVICE_INFO_HEADER(
            DISPLAYCONFIG_DEVICE_INFO_GET_TARGET_NAME,
            sizeof(TARGET_NAME),
            path.targetInfo.adapterId,
            path.targetInfo.id,
        )
        if (
            user32.DisplayConfigGetDeviceInfo(byref(source.header)) != 0
            or user32.DisplayConfigGetDeviceInfo(byref(target.header)) != 0
        ):
            continue
        device_name = str(source.viewGdiDeviceName)
        rect = bounds.get(device_name)
        if rect is None:
            continue
        width, height = rect[2] - rect[0], rect[3] - rect[1]
        result.append(
            _Display(
                ScreenSourceIdentity(
                    device_name,
                    str(target.monitorDevicePath),
                    str(target.monitorFriendlyDeviceName),
                    width,
                    height,
                ),
                rect,
            )
        )
    return tuple(result)


def _interactive_desktop_available() -> bool:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    if user32.GetSystemMetrics(SM_REMOTESESSION):
        return False
    desktop = user32.OpenInputDesktop(0, False, 0x0100)
    if not desktop:
        return False
    user32.CloseDesktop(desktop)
    wts = ctypes.WinDLL("wtsapi32", use_last_error=True)
    buffer, size = c_void_p(), c_ulong()
    if not wts.WTSQuerySessionInformationW(
        WTS_CURRENT_SERVER_HANDLE,
        WTS_CURRENT_SESSION,
        WTS_SESSION_INFO_EX,
        byref(buffer),
        byref(size),
    ):
        return False
    try:
        if size.value < sizeof(WTSINFOEX):
            return False
        info = ctypes.cast(buffer, POINTER(WTSINFOEX)).contents
        return info.Level == 1 and info.Data.level1.SessionFlags == 1
    finally:
        wts.WTSFreeMemory(buffer)


class WindowsScreenSource:
    def __init__(self) -> None:
        self._display: _Display | None = None

    @staticmethod
    def sources() -> tuple[ScreenSourceIdentity, ...]:
        try:
            return tuple(item.identity for item in _enumerate_displays())
        except Exception as error:
            raise LiveVisionViolation(
                "VISION-SCREEN-ENUMERATION-FAILED", "Windows display enumeration failed"
            ) from error

    async def open(
        self, source: VisualSourceIdentity, format: VisualCaptureFormat
    ) -> None:
        if not isinstance(source, ScreenSourceIdentity):
            raise LiveVisionViolation(
                "VISION-SOURCE-IDENTITY", "screen source identity required"
            )
        matches = [item for item in _enumerate_displays() if item.identity == source]
        if len(matches) != 1 or (format.width, format.height) != (
            source.width,
            source.height,
        ):
            raise LiveVisionViolation(
                "VISION-SCREEN-IDENTITY-MISMATCH",
                "exact display is unavailable or changed size",
            )
        if not _interactive_desktop_available():
            raise LiveVisionViolation(
                "VISION-DESKTOP-UNAVAILABLE", "interactive desktop is unavailable"
            )
        self._display = matches[0]

    async def next_frame(self) -> VisualFrame:
        display = self._display
        if display is None:
            raise LiveVisionViolation("VISION-SCREEN-CLOSED", "screen source is closed")
        if not _interactive_desktop_available():
            raise LiveVisionViolation(
                "VISION-DESKTOP-UNAVAILABLE", "interactive desktop is unavailable"
            )
        current = [
            item for item in _enumerate_displays() if item.identity == display.identity
        ]
        if len(current) != 1 or current[0].bounds != display.bounds:
            raise LiveVisionViolation(
                "VISION-SCREEN-IDENTITY-MISMATCH", "display identity changed"
            )
        image = await asyncio.to_thread(
            ImageGrab.grab, bbox=display.bounds, all_screens=True
        )
        if image.size != (display.identity.width, display.identity.height):
            raise LiveVisionViolation(
                "VISION-SCREEN-SIZE-MISMATCH", "captured display size changed"
            )
        image = image.convert("RGB")
        jpeg_io = BytesIO()
        image.save(jpeg_io, format="JPEG", quality=88)
        thumbnail = image.convert("L").resize((160, 90))
        preview = image.copy()
        preview.thumbnail((640, 640))
        preview_io = BytesIO()
        preview.save(preview_io, format="JPEG", quality=82)
        return VisualFrame(
            datetime.now(UTC),
            jpeg_io.getvalue(),
            image.width,
            image.height,
            thumbnail.tobytes(),
            preview_io.getvalue(),
        )

    async def close(self) -> None:
        self._display = None


__all__ = ("WindowsScreenSource",)
