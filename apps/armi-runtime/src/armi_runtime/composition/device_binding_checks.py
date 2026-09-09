"""Compare configured device identities with enumeration, without capture."""

from collections.abc import Callable
from dataclasses import asdict
from typing import Any

from armi_live_vision.api import LiveVisionViolation
from armi_live_voice.api import LiveVoiceViolation
from armi_local_control.configuration.models import RuntimeConfig

from armi_runtime.adapters.vision.directshow import DirectShowUsbCamera
from armi_runtime.adapters.vision.windows_screen import WindowsScreenSource
from armi_runtime.adapters.voice.wasapi import WasapiRawAudio


def inspect_device_bindings(
    config: RuntimeConfig,
    *,
    audio_devices: Callable[[], tuple[Any, ...]] = WasapiRawAudio.devices,
    cameras: Callable[[], tuple[Any, ...]] = DirectShowUsbCamera.sources,
    screens: Callable[[], tuple[Any, ...]] = WindowsScreenSource.sources,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    audio: tuple[Any, ...] | None = None

    def inspect(
        component: str,
        enabled: bool,
        identity: dict[str, Any] | None,
        enumerate_devices: Callable[[], tuple[Any, ...]],
        direction: str | None = None,
    ) -> None:
        nonlocal audio
        check: dict[str, Any] = {
            "component": component,
            "configured_identity": identity,
        }
        if not enabled:
            checks.append({**check, "binding_status": "disabled", "match_count": None})
            return
        if identity is None:
            checks.append(
                {**check, "binding_status": "not_configured", "match_count": None}
            )
            return
        try:
            if direction is not None:
                if audio is None:
                    audio = enumerate_devices()
                devices = audio
            else:
                devices = enumerate_devices()
            candidates = [asdict(device) for device in devices]
            matches = [
                device
                for device in candidates
                if all(device.get(key) == value for key, value in identity.items())
                and (direction is None or device[direction + "_channels"] > 0)
            ]
            checks.append(
                {
                    **check,
                    "binding_status": "matches"
                    if len(matches) == 1
                    else "ambiguous"
                    if matches
                    else "missing",
                    "match_count": len(matches),
                }
            )
        except (
            LiveVisionViolation,
            LiveVoiceViolation,
            OSError,
            ImportError,
            RuntimeError,
            ValueError,
        ):
            checks.append(
                {
                    **check,
                    "binding_status": "unavailable",
                    "match_count": None,
                    "error_code": "DEVICE-ENUMERATION-UNAVAILABLE",
                }
            )

    for direction in ("input", "output"):
        device = (
            config.voice.input_device
            if direction == "input"
            else config.voice.output_device
        )
        inspect(
            "voice." + direction,
            config.voice.enabled,
            None if device is None else device.model_dump(mode="json"),
            audio_devices,
            direction,
        )
    for kind, source, enumerate_devices in (
        ("camera", config.vision.camera, cameras),
        ("screen", config.vision.screen, screens),
    ):
        inspect(
            "vision." + kind,
            source.enabled,
            None
            if source.identity is None
            else source.identity.model_dump(mode="json"),
            enumerate_devices,
        )
    return checks


__all__ = ("inspect_device_bindings",)
