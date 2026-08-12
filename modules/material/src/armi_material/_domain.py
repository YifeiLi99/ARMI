"""Private life-material invariants."""

from __future__ import annotations

import re

_METADATA_KEY = re.compile(r"^[a-z][a-z0-9._-]{0,63}$", re.ASCII)


def valid_metadata(value: tuple[tuple[str, str], ...]) -> bool:
    return (
        type(value) is tuple
        and len(value) <= 32
        and all(
            type(key) is str
            and _METADATA_KEY.fullmatch(key) is not None
            and type(item) is str
            and len(item) <= 512
            and "\x00" not in item
            for key, item in value
        )
        and tuple(sorted(value)) == value
        and len({key for key, _ in value}) == len(value)
    )


__all__ = ()
