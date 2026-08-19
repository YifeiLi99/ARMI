"""Strict environment configuration for the optional mood display."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from armi_kernel import load_yaml_file

from .api import MoodDisplayConfig, MoodDisplayViolation

_FIELDS = frozenset({"schema_version", "enabled", "port", "expected_device_id"})


def load_mood_display_config(environment_root: Path) -> MoodDisplayConfig | None:
    path = environment_root / "devices" / "mood-display.yaml"
    if not path.exists():
        return None
    try:
        raw = cast(object, load_yaml_file(path))
    except (OSError, UnicodeError, ValueError) as error:
        raise MoodDisplayViolation("MOOD-DISPLAY-CONFIG") from error
    if not isinstance(raw, dict):
        raise MoodDisplayViolation("MOOD-DISPLAY-CONFIG")
    document = cast(dict[str, object], raw)
    if frozenset(document) != _FIELDS:
        raise MoodDisplayViolation("MOOD-DISPLAY-CONFIG")
    if document.get("schema_version") != "armi.mood-display-config.v1":
        raise MoodDisplayViolation("MOOD-DISPLAY-CONFIG")
    enabled = document.get("enabled")
    port = document.get("port")
    expected = document.get("expected_device_id")
    if type(enabled) is not bool or not isinstance(port, str) or not port.strip():
        raise MoodDisplayViolation("MOOD-DISPLAY-CONFIG")
    if not isinstance(expected, str) or not expected.strip() or len(expected) > 64:
        raise MoodDisplayViolation("MOOD-DISPLAY-CONFIG")
    return MoodDisplayConfig(enabled, port.strip(), expected.strip())


__all__ = ("load_mood_display_config",)
