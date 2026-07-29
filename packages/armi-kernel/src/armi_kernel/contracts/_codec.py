"""Private strict-wire helpers for the public transport contract."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from types import MappingProxyType
from typing import cast

CONTRACT_VERSION = "1.0"
MAX_SAFE_INTEGER = 9_007_199_254_740_991
MAX_JSON_DEPTH = 8
MAX_JSON_CONTAINER_ITEMS = 64
MAX_JSON_KEY_LENGTH = 64
MAX_JSON_STRING_LENGTH = 4096

type JsonPrimitive = bool | int | float | str | None
type FrozenJson = JsonPrimitive | tuple[FrozenJson, ...] | Mapping[str, FrozenJson]


class ContractViolation(ValueError):
    """A stable rejection raised when a public wire contract is violated."""

    __slots__ = ("code", "message", "path")

    def __init__(self, code: str, message: str, *, path: str = "$") -> None:
        self.code = code
        self.message = message
        self.path = path
        super().__init__(f"{code} at {path}: {message}")


def require_mapping(value: object, *, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ContractViolation("CON-TYPE", "expected an object", path=path)
    raw = cast(Mapping[object, object], value)
    result: dict[str, object] = {}
    for key, item in raw.items():
        if not isinstance(key, str):
            raise ContractViolation(
                "CON-JSON", "object keys must be strings", path=path
            )
        result[key] = item
    return result


def require_exact_fields(
    value: Mapping[str, object],
    *,
    required: frozenset[str],
    optional: frozenset[str] = frozenset(),
    path: str,
) -> None:
    present = frozenset(value)
    missing = sorted(required - present)
    if missing:
        raise ContractViolation(
            "CON-FIELD-MISSING",
            f"missing field(s): {', '.join(missing)}",
            path=path,
        )
    unknown = sorted(present - required - optional)
    if unknown:
        raise ContractViolation(
            "CON-FIELD-UNKNOWN",
            f"unknown field(s): {', '.join(unknown)}",
            path=path,
        )


def require_contract_version(value: object, *, path: str) -> None:
    if value != CONTRACT_VERSION or not isinstance(value, str):
        raise ContractViolation(
            "CON-VERSION",
            f"contract_version must be exactly {CONTRACT_VERSION!r}",
            path=path,
        )


def require_string(
    value: object,
    *,
    path: str,
    minimum: int = 1,
    maximum: int = MAX_JSON_STRING_LENGTH,
) -> str:
    if not isinstance(value, str):
        raise ContractViolation("CON-TYPE", "expected a string", path=path)
    if not minimum <= len(value) <= maximum:
        raise ContractViolation(
            "CON-TOKEN",
            f"string length must be between {minimum} and {maximum}",
            path=path,
        )
    return value


def require_ascii_token(
    value: object,
    *,
    path: str,
    maximum: int,
    lowercase: bool,
) -> str:
    token = require_string(value, path=path, maximum=maximum)
    pattern = r"[a-z][a-z0-9._:-]*" if lowercase else r"[A-Za-z0-9][A-Za-z0-9._~:-]*"
    if re.fullmatch(pattern, token, flags=re.ASCII) is None:
        raise ContractViolation(
            "CON-TOKEN", "expected a bounded ASCII token", path=path
        )
    return token


def freeze_json(
    value: object,
    *,
    path: str,
    depth: int = 0,
) -> FrozenJson:
    if depth > MAX_JSON_DEPTH:
        raise ContractViolation(
            "CON-JSON",
            f"JSON nesting exceeds {MAX_JSON_DEPTH}",
            path=path,
        )
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        if not -MAX_SAFE_INTEGER <= value <= MAX_SAFE_INTEGER:
            raise ContractViolation(
                "CON-JSON",
                "integer is outside the JavaScript safe range",
                path=path,
            )
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ContractViolation("CON-JSON", "number must be finite", path=path)
        return value
    if isinstance(value, str):
        if len(value) > MAX_JSON_STRING_LENGTH:
            raise ContractViolation(
                "CON-JSON",
                f"string exceeds {MAX_JSON_STRING_LENGTH} characters",
                path=path,
            )
        return value
    if isinstance(value, (list, tuple)):
        sequence = cast(list[object] | tuple[object, ...], value)
        if len(sequence) > MAX_JSON_CONTAINER_ITEMS:
            raise ContractViolation(
                "CON-JSON",
                f"array exceeds {MAX_JSON_CONTAINER_ITEMS} items",
                path=path,
            )
        return tuple(
            freeze_json(item, path=f"{path}[{index}]", depth=depth + 1)
            for index, item in enumerate(sequence)
        )
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        if len(mapping) > MAX_JSON_CONTAINER_ITEMS:
            raise ContractViolation(
                "CON-JSON",
                f"object exceeds {MAX_JSON_CONTAINER_ITEMS} fields",
                path=path,
            )
        frozen: dict[str, FrozenJson] = {}
        for key, item in mapping.items():
            if not isinstance(key, str):
                raise ContractViolation(
                    "CON-JSON", "object keys must be strings", path=path
                )
            if len(key) > MAX_JSON_KEY_LENGTH:
                raise ContractViolation(
                    "CON-JSON",
                    f"object key exceeds {MAX_JSON_KEY_LENGTH} characters",
                    path=path,
                )
            frozen[key] = freeze_json(item, path=f"{path}.{key}", depth=depth + 1)
        return MappingProxyType(frozen)
    raise ContractViolation(
        "CON-JSON",
        f"value of type {type(value).__name__!r} is not JSON-safe",
        path=path,
    )


def thaw_json(value: FrozenJson) -> object:
    if isinstance(value, Mapping):
        return {key: thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw_json(item) for item in value]
    return value


def optional_details(
    value: object,
    *,
    path: str,
) -> Mapping[str, FrozenJson]:
    mapping = require_mapping(value, path=path)
    frozen = freeze_json(mapping, path=path)
    if not isinstance(frozen, Mapping):
        raise ContractViolation("CON-JSON", "details must be an object", path=path)
    return frozen
