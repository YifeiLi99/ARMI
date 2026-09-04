"""Exact USB camera enumeration and capture through Windows DirectShow."""

# pyright: reportAttributeAccessIssue=false, reportIncompatibleVariableOverride=false, reportMissingTypeStubs=false, reportPrivateUsage=false, reportUnknownArgumentType=false, reportUnknownMemberType=false, reportUnknownVariableType=false

from __future__ import annotations

import asyncio
import ctypes
from ctypes import POINTER, byref, c_ulong, c_void_p
from datetime import UTC, datetime
from importlib import import_module
from typing import Any, ClassVar

from armi_live_vision.api import (
    CameraSourceIdentity,
    LiveVisionViolation,
    VisualCaptureFormat,
    VisualFrame,
    VisualSourceIdentity,
)

_SYSTEM_DEVICE_ENUM = "{62BE5D10-60EB-11D0-BD3B-00A0C911CE86}"
_VIDEO_INPUT_CATEGORY = "{860BB310-5D01-11D0-BD3B-00A0C911CE86}"
_LOCATION_PATHS_FMTID = "{A45C254E-DF1C-4EFD-8020-67D146A850E0}"
_LOCATION_PATHS_PID = 37
_DEVPROP_TYPE_STRING_LIST = 0x00002012
_CR_SUCCESS = 0
_CR_BUFFER_SMALL = 0x1A


def _directshow_monikers() -> tuple[tuple[str, str], ...]:
    """Use the System Device Enumerator without quartz typelib constants."""
    from comtypes import COMMETHOD, GUID, HRESULT, IUnknown
    from comtypes.automation import VARIANT
    from comtypes.client import CreateObject
    from comtypes.persist import IPropertyBag

    class IMoniker(IUnknown):
        _iid_ = GUID("{0000000F-0000-0000-C000-000000000046}")

    IMoniker._methods_ = [
        COMMETHOD([], HRESULT, "GetClassID", (["out"], POINTER(GUID), "class_id")),
        COMMETHOD([], HRESULT, "IsDirty"),
        COMMETHOD([], HRESULT, "Load", (["in"], c_void_p, "stream")),
        COMMETHOD(
            [],
            HRESULT,
            "Save",
            (["in"], c_void_p, "stream"),
            (["in"], ctypes.c_int, "clear_dirty"),
        ),
        COMMETHOD([], HRESULT, "GetSizeMax", (["out"], c_void_p, "size")),
        COMMETHOD(
            [],
            HRESULT,
            "BindToObject",
            (["in"], c_void_p, "bind_ctx"),
            (["in"], c_void_p, "left"),
            (["in"], POINTER(GUID), "iid"),
            (["out"], POINTER(c_void_p), "object"),
        ),
        COMMETHOD(
            [],
            HRESULT,
            "BindToStorage",
            (["in"], c_void_p, "bind_ctx"),
            (["in"], c_void_p, "left"),
            (["in"], POINTER(GUID), "iid"),
            (["out"], POINTER(POINTER(IPropertyBag)), "object"),
        ),
        COMMETHOD(
            [],
            HRESULT,
            "Reduce",
            (["in"], c_void_p, "bind_ctx"),
            (["in"], c_ulong, "how_far"),
            (["in", "out"], POINTER(c_void_p), "left"),
            (["out"], POINTER(c_void_p), "reduced"),
        ),
        COMMETHOD(
            [],
            HRESULT,
            "ComposeWith",
            (["in"], c_void_p, "right"),
            (["in"], ctypes.c_int, "only_if_not_generic"),
            (["out"], POINTER(c_void_p), "composite"),
        ),
        COMMETHOD(
            [],
            HRESULT,
            "Enum",
            (["in"], ctypes.c_int, "forward"),
            (["out"], POINTER(c_void_p), "enumerator"),
        ),
        COMMETHOD([], HRESULT, "IsEqual", (["in"], c_void_p, "other")),
        COMMETHOD([], HRESULT, "Hash", (["out"], POINTER(c_ulong), "hash_value")),
        COMMETHOD(
            [],
            HRESULT,
            "IsRunning",
            (["in"], c_void_p, "bind_ctx"),
            (["in"], c_void_p, "left"),
            (["in"], c_void_p, "newly_running"),
        ),
        COMMETHOD(
            [],
            HRESULT,
            "GetTimeOfLastChange",
            (["in"], c_void_p, "bind_ctx"),
            (["in"], c_void_p, "left"),
            (["out"], c_void_p, "file_time"),
        ),
        COMMETHOD([], HRESULT, "Inverse", (["out"], POINTER(c_void_p), "inverse")),
        COMMETHOD(
            [],
            HRESULT,
            "CommonPrefixWith",
            (["in"], c_void_p, "other"),
            (["out"], POINTER(c_void_p), "prefix"),
        ),
        COMMETHOD(
            [],
            HRESULT,
            "RelativePathTo",
            (["in"], c_void_p, "other"),
            (["out"], POINTER(c_void_p), "relative"),
        ),
        COMMETHOD(
            [],
            HRESULT,
            "GetDisplayName",
            (["in"], c_void_p, "bind_ctx"),
            (["in"], c_void_p, "left"),
            (["out"], POINTER(ctypes.c_wchar_p), "display_name"),
        ),
        COMMETHOD(
            [],
            HRESULT,
            "ParseDisplayName",
            (["in"], c_void_p, "bind_ctx"),
            (["in"], c_void_p, "left"),
            (["in"], ctypes.c_wchar_p, "name"),
            (["out"], POINTER(c_ulong), "eaten"),
            (["out"], POINTER(c_void_p), "parsed"),
        ),
        COMMETHOD([], HRESULT, "IsSystemMoniker", (["out"], POINTER(c_ulong), "kind")),
    ]

    class IEnumMoniker(IUnknown):
        _iid_ = GUID("{00000102-0000-0000-C000-000000000046}")
        _methods_: ClassVar[list[object]] = [
            COMMETHOD(
                [],
                HRESULT,
                "Next",
                (["in"], c_ulong, "count"),
                (["out"], POINTER(POINTER(IMoniker)), "moniker"),
                (["out"], POINTER(c_ulong), "fetched"),
            ),
            COMMETHOD([], HRESULT, "Skip", (["in"], c_ulong, "count")),
            COMMETHOD([], HRESULT, "Reset"),
            COMMETHOD([], HRESULT, "Clone", (["out"], POINTER(c_void_p), "clone")),
        ]

    class ICreateDevEnum(IUnknown):
        _iid_ = GUID("{29840822-5B84-11D0-BD3B-00A0C911CE86}")
        _methods_: ClassVar[list[object]] = [
            COMMETHOD(
                [],
                HRESULT,
                "CreateClassEnumerator",
                (["in"], POINTER(GUID), "category"),
                (["out"], POINTER(POINTER(IEnumMoniker)), "enumerator"),
                (["in"], c_ulong, "flags"),
            )
        ]

    system_enum = CreateObject(GUID(_SYSTEM_DEVICE_ENUM), interface=ICreateDevEnum)
    category = GUID(_VIDEO_INPUT_CATEGORY)
    enum_ptr = system_enum.CreateClassEnumerator(byref(category), 0)
    if not enum_ptr:
        return ()
    values: list[tuple[str, str]] = []
    while True:
        try:
            result = enum_ptr.Next(1)
        except OSError, StopIteration:
            break
        moniker = result[0] if isinstance(result, tuple) else result
        if not moniker:
            break
        bag = moniker.BindToStorage(None, None, byref(IPropertyBag._iid_))
        friendly_value = VARIANT()
        friendly = str(bag.Read("FriendlyName", friendly_value, None))
        try:
            path_value = VARIANT()
            device_path = str(bag.Read("DevicePath", path_value, None))
        except Exception:
            device_path = str(moniker.GetDisplayName(None, None))
        values.append((friendly, device_path))
    return tuple(values)


def _pnp_instance_id(device_path: str) -> str | None:
    value = device_path.casefold()
    marker = value.find("usb#")
    if marker < 0:
        return None
    parts = device_path[marker:].split("#")
    if len(parts) < 3:
        return None
    return "\\".join(parts[:3]).upper()


def _location_paths(instance_id: str) -> tuple[str, ...]:
    cfg = ctypes.WinDLL("cfgmgr32", use_last_error=True)

    class GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", ctypes.c_uint32),
            ("Data2", ctypes.c_uint16),
            ("Data3", ctypes.c_uint16),
            ("Data4", ctypes.c_ubyte * 8),
        ]

    class DEVPROPKEY(ctypes.Structure):
        _fields_ = [("fmtid", GUID), ("pid", ctypes.c_ulong)]

    fmtid = GUID()
    if ctypes.WinDLL("ole32").CLSIDFromString(_LOCATION_PATHS_FMTID, byref(fmtid)) != 0:
        return ()
    key = DEVPROPKEY(fmtid, _LOCATION_PATHS_PID)
    devinst = ctypes.c_ulong()
    if cfg.CM_Locate_DevNodeW(byref(devinst), instance_id, 0) != _CR_SUCCESS:
        return ()
    prop_type = ctypes.c_ulong()
    size = ctypes.c_ulong()
    rc = cfg.CM_Get_DevNode_PropertyW(
        devinst, byref(key), byref(prop_type), None, byref(size), 0
    )
    if rc not in {_CR_SUCCESS, _CR_BUFFER_SMALL} or size.value == 0:
        return ()
    buffer = (ctypes.c_byte * size.value)()
    rc = cfg.CM_Get_DevNode_PropertyW(
        devinst, byref(key), byref(prop_type), buffer, byref(size), 0
    )
    if rc != _CR_SUCCESS or prop_type.value != _DEVPROP_TYPE_STRING_LIST:
        return ()
    text = ctypes.wstring_at(
        ctypes.addressof(buffer), size.value // ctypes.sizeof(ctypes.c_wchar)
    )
    return tuple(item for item in text.split("\0") if item)


class DirectShowUsbCamera:
    def __init__(self) -> None:
        self._capture: Any = None

    @staticmethod
    def sources() -> tuple[CameraSourceIdentity, ...]:
        try:
            devices: list[CameraSourceIdentity] = []
            seen: set[tuple[str, str]] = set()
            for name, device_path in _directshow_monikers():
                instance_id = _pnp_instance_id(device_path)
                paths = () if instance_id is None else _location_paths(instance_id)
                if not paths or (device_path, paths[0]) in seen:
                    continue
                seen.add((device_path, paths[0]))
                devices.append(CameraSourceIdentity(name, device_path, paths[0]))
            return tuple(devices)
        except Exception as error:
            raise LiveVisionViolation(
                "VISION-ENUMERATION-FAILED", "DirectShow camera enumeration failed"
            ) from error

    async def open(
        self, source: VisualSourceIdentity, format: VisualCaptureFormat
    ) -> None:
        if not isinstance(source, CameraSourceIdentity):
            raise LiveVisionViolation(
                "VISION-SOURCE-IDENTITY", "camera source identity required"
            )
        matches = [index for index, item in enumerate(self.sources()) if item == source]
        if len(matches) != 1:
            raise LiveVisionViolation(
                "VISION-DEVICE-UNAVAILABLE", "exact camera is unavailable"
            )
        cv2: Any = import_module("cv2")
        capture = cv2.VideoCapture(matches[0], cv2.CAP_DSHOW)
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, format.width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, format.height)
        capture.set(cv2.CAP_PROP_FPS, format.fps)
        if (
            not capture.isOpened()
            or int(capture.get(cv2.CAP_PROP_BACKEND)) != cv2.CAP_DSHOW
        ):
            capture.release()
            raise LiveVisionViolation(
                "VISION-DSHOW-OPEN-FAILED", "DirectShow did not open exact camera"
            )
        actual = (
            round(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
            round(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        )
        if actual != (format.width, format.height):
            capture.release()
            raise LiveVisionViolation(
                "VISION-CAPTURE-FORMAT", "camera rejected required format"
            )
        self._capture = capture

    async def next_frame(self) -> VisualFrame:
        if self._capture is None:
            raise LiveVisionViolation("VISION-CAMERA-CLOSED", "camera is closed")
        ok, image = await asyncio.to_thread(self._capture.read)
        if not ok or image is None:
            raise LiveVisionViolation(
                "VISION-CAMERA-DISCONNECTED", "camera frame read failed"
            )
        cv2: Any = import_module("cv2")
        encoded, jpeg = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 88])
        if not encoded:
            raise LiveVisionViolation(
                "VISION-JPEG-FAILED", "camera frame encoding failed"
            )
        height, width = image.shape[:2]
        thumbnail = cv2.resize(
            cv2.cvtColor(image, cv2.COLOR_BGR2GRAY),
            (160, 90),
            interpolation=cv2.INTER_AREA,
        )
        preview_image = cv2.resize(image, (640, 360), interpolation=cv2.INTER_AREA)
        preview_encoded, preview = cv2.imencode(
            ".jpg", preview_image, [cv2.IMWRITE_JPEG_QUALITY, 82]
        )
        if not preview_encoded:
            raise LiveVisionViolation(
                "VISION-JPEG-FAILED", "camera preview encoding failed"
            )
        return VisualFrame(
            datetime.now(UTC),
            jpeg.tobytes(),
            width,
            height,
            thumbnail.tobytes(),
            preview.tobytes(),
        )

    async def close(self) -> None:
        capture, self._capture = self._capture, None
        if capture is not None:
            await asyncio.to_thread(capture.release)


__all__ = ("DirectShowUsbCamera",)
