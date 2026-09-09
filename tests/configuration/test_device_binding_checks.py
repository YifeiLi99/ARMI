from types import SimpleNamespace
from typing import cast

import pytest
from armi_live_voice.api import AudioDevice
from armi_local_control.configuration.models import (
    RuntimeConfig,
    VisionConfig,
    VoiceConfig,
    VoiceDeviceConfig,
)
from armi_runtime.composition.device_binding_checks import inspect_device_bindings


def test_disabled_devices_are_not_enumerated() -> None:
    config = cast(
        RuntimeConfig, SimpleNamespace(voice=VoiceConfig(), vision=VisionConfig())
    )

    def forbidden():
        pytest.fail("disabled diagnostics must not touch devices")

    checks = inspect_device_bindings(
        config, audio_devices=forbidden, cameras=forbidden, screens=forbidden
    )
    assert all(item["binding_status"] == "disabled" for item in checks)


def test_voice_binding_checks_identity_direction_and_ambiguity() -> None:
    config = cast(
        RuntimeConfig,
        SimpleNamespace(
            voice=VoiceConfig(
                enabled=True,
                input_device=VoiceDeviceConfig(
                    host_api="Windows WASAPI", name="microphone"
                ),
                output_device=VoiceDeviceConfig(
                    host_api="Windows WASAPI", name="speaker"
                ),
            ),
            vision=VisionConfig(),
        ),
    )
    microphone = AudioDevice("Windows WASAPI", "microphone", 1, 0, 16000.0)
    calls = []

    def devices():
        calls.append(True)
        return (microphone,)

    checks = inspect_device_bindings(config, audio_devices=devices)
    assert [item["binding_status"] for item in checks[:2]] == ["matches", "missing"]
    assert calls == [True]
    ambiguous = inspect_device_bindings(
        config, audio_devices=lambda: (microphone, microphone)
    )
    assert ambiguous[0]["binding_status"] == "ambiguous"

    def unavailable():
        raise OSError("native enumeration failed")

    failed = inspect_device_bindings(config, audio_devices=unavailable)
    assert failed[0]["binding_status"] == "unavailable"
    assert "native enumeration failed" not in str(failed)
