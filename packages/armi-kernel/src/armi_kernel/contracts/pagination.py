"""Strict pagination request and response values."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Self, cast

from ._codec import (
    CONTRACT_VERSION,
    ContractViolation,
    require_contract_version,
    require_exact_fields,
    require_mapping,
)
from .values import OpaqueCursor


@dataclass(frozen=True, slots=True)
class PageRequest:
    limit: int
    cursor: OpaqueCursor | None = None

    def __post_init__(self) -> None:
        if type(self.limit) is not int or not 1 <= self.limit <= 100:
            raise ContractViolation(
                "CON-PAGE", "limit must be an integer from 1 to 100"
            )

    @classmethod
    def from_wire(cls, value: object, *, path: str = "$") -> Self:
        wire = require_mapping(value, path=path)
        require_exact_fields(
            wire,
            required=frozenset({"contract_version", "limit"}),
            optional=frozenset({"cursor"}),
            path=path,
        )
        require_contract_version(
            wire["contract_version"], path=f"{path}.contract_version"
        )
        limit = wire["limit"]
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 100
        ):
            raise ContractViolation(
                "CON-PAGE",
                "limit must be an integer from 1 to 100",
                path=f"{path}.limit",
            )
        return cls(
            limit,
            OpaqueCursor.from_wire(wire["cursor"], path=f"{path}.cursor")
            if "cursor" in wire
            else None,
        )

    def to_wire(self) -> dict[str, object]:
        wire: dict[str, object] = {
            "contract_version": CONTRACT_VERSION,
            "limit": self.limit,
        }
        if self.cursor is not None:
            wire["cursor"] = self.cursor.to_wire()
        return wire


@dataclass(frozen=True, slots=True)
class Page[ItemT]:
    items: tuple[ItemT, ...]
    next_cursor: OpaqueCursor | None = None

    def __post_init__(self) -> None:
        if type(self.items) is not tuple:
            raise ContractViolation("CON-PAGE", "items must be an immutable tuple")

    @classmethod
    def from_wire(
        cls,
        value: object,
        *,
        item_decoder: Callable[[object], ItemT],
        path: str = "$",
    ) -> Self:
        wire = require_mapping(value, path=path)
        require_exact_fields(
            wire,
            required=frozenset({"contract_version", "items"}),
            optional=frozenset({"next_cursor"}),
            path=path,
        )
        require_contract_version(
            wire["contract_version"], path=f"{path}.contract_version"
        )
        raw_items = wire["items"]
        if not isinstance(raw_items, list):
            raise ContractViolation(
                "CON-PAGE", "items must be a JSON array", path=f"{path}.items"
            )
        item_values = cast(list[object], raw_items)
        decoded: list[ItemT] = []
        for index, item in enumerate(item_values):
            try:
                decoded.append(item_decoder(item))
            except ContractViolation:
                raise
            except Exception as error:
                raise ContractViolation(
                    "CON-PAYLOAD",
                    "item decoder rejected the page item",
                    path=f"{path}.items[{index}]",
                ) from error
        return cls(
            tuple(decoded),
            OpaqueCursor.from_wire(wire["next_cursor"], path=f"{path}.next_cursor")
            if "next_cursor" in wire
            else None,
        )

    def to_wire(self, *, item_encoder: Callable[[ItemT], object]) -> dict[str, object]:
        items: Sequence[object] = tuple(item_encoder(item) for item in self.items)
        wire: dict[str, object] = {
            "contract_version": CONTRACT_VERSION,
            "items": list(items),
        }
        if self.next_cursor is not None:
            wire["next_cursor"] = self.next_cursor.to_wire()
        return wire
