"""Bridge JSON container semantics to strict Pydantic model containers."""

from __future__ import annotations

from typing import cast


def strict_model_value(value: object) -> object:
    """Preserve JSON scalars while mapping JSON arrays to tuple contracts."""

    if isinstance(value, list):
        items = cast(list[object], value)
        return tuple(strict_model_value(item) for item in items)
    if isinstance(value, dict):
        items = cast(dict[str, object], value)
        return {key: strict_model_value(item) for key, item in items.items()}
    return value


__all__ = ()
