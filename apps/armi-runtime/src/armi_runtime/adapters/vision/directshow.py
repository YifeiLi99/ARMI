"""Exact USB camera enumeration and capture through Windows DirectShow."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from importlib import import_module
from typing import Any, cast

from armi_live_vision.api import (
    CameraDevice,
    CameraFormat,
    CameraFrame,
    LiveVisionViolation,
)


class DirectShowUsbCamera:
    def __init__(self) -> None:
        self._capture: Any = None

    @staticmethod
    def devices() -> tuple[CameraDevice, ...]:
        """Enumerate DirectShow monikers over COM and attach exact USB location."""
        try:
            client: Any = import_module("comtypes.client")

            quartz = client.GetModule("quartz.dll")
            system_enum = client.CreateObject(
                quartz.CLSID_SystemDeviceEnum,
                interface=quartz.ICreateDevEnum,
            )
            moniker_enum = system_enum.CreateClassEnumerator(
                quartz.CLSID_VideoInputDeviceCategory, 0
            )
            display_paths: list[str] = []
            while True:
                try:
                    moniker: Any = moniker_enum.Next(1)
                except OSError, StopIteration:
                    break
                if moniker is None:
                    break
                if isinstance(moniker, tuple):
                    if not moniker:
                        break
                    moniker = cast(tuple[Any, ...], moniker)[0]
                display_paths.append(str(moniker.GetDisplayName(None, None)))

            locator = client.CreateObject("WbemScripting.SWbemLocator")
            service = locator.ConnectServer(".", "root\\cimv2")
            rows = service.ExecQuery(
                "SELECT Name,DeviceID,LocationInformation FROM Win32_PnPEntity "
                "WHERE PNPClass='Camera' OR PNPClass='Image'"
            )
            pnp_rows = tuple(rows)
            devices: list[CameraDevice] = []
            for display_path in display_paths:
                normalized = display_path.casefold().replace("#", "\\")
                matches = [
                    row
                    for row in pnp_rows
                    if row.DeviceID
                    and str(row.DeviceID).casefold() in normalized
                    and row.LocationInformation
                ]
                if len(matches) != 1:
                    continue
                devices.append(
                    CameraDevice(
                        name=str(matches[0].Name),
                        device_path=display_path,
                        usb_location_id=str(matches[0].LocationInformation),
                    )
                )
            return tuple(devices)
        except Exception as error:
            raise LiveVisionViolation(
                "VISION-ENUMERATION-FAILED", "DirectShow camera enumeration failed"
            ) from error

    async def open(self, device: CameraDevice, format: CameraFormat) -> None:
        devices = self.devices()
        matches = [
            index
            for index, item in enumerate(devices)
            if item.device_path == device.device_path
            and item.usb_location_id == device.usb_location_id
        ]
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

    async def next_frame(self) -> CameraFrame:
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
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        thumbnail = cv2.resize(gray, (160, 90), interpolation=cv2.INTER_AREA)
        preview_image = cv2.resize(image, (640, 360), interpolation=cv2.INTER_AREA)
        preview_encoded, preview = cv2.imencode(
            ".jpg", preview_image, [cv2.IMWRITE_JPEG_QUALITY, 82]
        )
        if not preview_encoded:
            raise LiveVisionViolation(
                "VISION-JPEG-FAILED", "camera preview encoding failed"
            )
        return CameraFrame(
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
