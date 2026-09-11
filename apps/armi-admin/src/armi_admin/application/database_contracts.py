"""Structured database operations; identifiers and predicates are never SQL."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from .contracts import EnvironmentRequest

Identifier = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,62}$")]


class DatabaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class DatabaseFilter(DatabaseModel):
    field: Identifier
    operator: Literal["eq", "ne", "lt", "le", "gt", "ge", "in", "is_null"]
    value: JsonValue

    @model_validator(mode="after")
    def _operand(self) -> Self:
        if self.operator == "is_null" and not isinstance(self.value, bool):
            raise ValueError("ADMIN-DATABASE-NULL-PREDICATE")
        if self.operator == "in" and (
            not isinstance(self.value, list) or not 1 <= len(self.value) <= 200
        ):
            raise ValueError("ADMIN-DATABASE-IN-PREDICATE")
        if self.value is None and self.operator not in {"eq", "ne"}:
            raise ValueError("ADMIN-DATABASE-NULL-PREDICATE")
        return self


class DatabaseOrder(DatabaseModel):
    field: Identifier
    direction: Literal["asc", "desc"] = "asc"


class DatabaseCatalogRequest(EnvironmentRequest):
    table: Identifier | None = None


class DatabaseQueryRequest(EnvironmentRequest):
    table: Identifier
    fields: list[Identifier] = Field(default_factory=list, max_length=200)
    filters: list[DatabaseFilter] = Field(
        default_factory=list[DatabaseFilter], max_length=32
    )
    order: list[DatabaseOrder] = Field(
        default_factory=list[DatabaseOrder], max_length=16
    )
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0, le=1_000_000)


class DatabaseInsert(DatabaseModel):
    action: Literal["insert"]
    table: Identifier
    values: dict[Identifier, JsonValue] = Field(min_length=1, max_length=200)


class DatabaseUpdate(DatabaseModel):
    action: Literal["update"]
    table: Identifier
    key: dict[Identifier, JsonValue] = Field(min_length=1, max_length=32)
    expected_version: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    values: dict[Identifier, JsonValue] = Field(min_length=1, max_length=200)


class DatabaseDelete(DatabaseModel):
    action: Literal["delete"]
    table: Identifier
    key: dict[Identifier, JsonValue] = Field(min_length=1, max_length=32)
    expected_version: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


DatabaseChange = Annotated[
    DatabaseInsert | DatabaseUpdate | DatabaseDelete, Field(discriminator="action")
]


class DatabaseBatchRequest(EnvironmentRequest):
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9._:-]{1,128}$")
    changes: list[DatabaseChange] = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=1024)


__all__ = (
    "DatabaseBatchRequest",
    "DatabaseCatalogRequest",
    "DatabaseChange",
    "DatabaseDelete",
    "DatabaseFilter",
    "DatabaseInsert",
    "DatabaseOrder",
    "DatabaseQueryRequest",
    "DatabaseUpdate",
)
