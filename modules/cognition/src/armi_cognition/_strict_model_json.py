"""Bridge JSON container semantics to strict Pydantic model containers."""

from __future__ import annotations

from typing import cast


def strict_model_value(value: object) -> object:
    """Map JSON arrays and mathematically integral numbers to strict contract types."""

    # JSON Schema defines integer by value, so 60 and 60.0 have identical meaning.
    # Do not coerce booleans, numeric strings or fractional values.
    if type(value) is float and value.is_integer():
        return int(value)
    if isinstance(value, list):
        items = cast(list[object], value)
        return tuple(strict_model_value(item) for item in items)
    if isinstance(value, dict):
        items = cast(dict[str, object], value)
        return {key: strict_model_value(item) for key, item in items.items()}
    return value


__all__ = ()
