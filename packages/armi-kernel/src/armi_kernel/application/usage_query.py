"""Read-only metering query contract shared by authenticated transports."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from typing import Literal, Protocol
from uuid import UUID

BEIJING = timezone(timedelta(hours=8))


@dataclass(frozen=True, slots=True)
class UsageFilter:
    start: datetime
    end: datetime
    service: str | None = None
    model: str | None = None
    purpose: str | None = None
    outcome: str | None = None
    cost_status: str | None = None
    operation_id: str | None = None

    def __post_init__(self) -> None:
        if (
            self.start.tzinfo is None
            or self.end.tzinfo is None
            or self.end <= self.start
        ):
            raise ValueError("USAGE-TIME-RANGE")
        for value in (
            self.service,
            self.model,
            self.purpose,
            self.outcome,
            self.cost_status,
        ):
            if value is not None and (not value or len(value) > 128):
                raise ValueError("USAGE-FILTER")
        if self.operation_id is not None:
            UUID(self.operation_id)

    @classmethod
    def from_strings(
        cls,
        *,
        start: str | None = None,
        end: str | None = None,
        service: str | None = None,
        model: str | None = None,
        purpose: str | None = None,
        outcome: str | None = None,
        cost_status: str | None = None,
        operation_id: str | None = None,
    ) -> UsageFilter:
        now = datetime.now(BEIJING)
        first = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return cls(
            first if start is None else datetime.fromisoformat(start),
            datetime.now(UTC) if end is None else datetime.fromisoformat(end),
            service,
            model,
            purpose,
            outcome,
            cost_status,
            operation_id,
        )


@dataclass(frozen=True, slots=True)
class UsageQuery:
    mode: Literal["summary", "list", "read"]
    filters: UsageFilter
    limit: int = 25
    offset: int = 0
    call_id: str | None = None

    def __post_init__(self) -> None:
        if self.mode not in {"summary", "list", "read"}:
            raise ValueError("USAGE-QUERY-MODE")
        if (
            type(self.limit) is not int
            or not 1 <= self.limit <= 100
            or type(self.offset) is not int
            or self.offset < 0
        ):
            raise ValueError("USAGE-PAGINATION")
        if self.mode == "read":
            if self.call_id is None:
                raise ValueError("USAGE-CALL-ID")
            UUID(self.call_id)
        elif self.call_id is not None:
            raise ValueError("USAGE-CALL-ID")


class UsageQueryPort(Protocol):
    async def query(self, request: UsageQuery) -> dict[str, object]: ...


__all__ = ("UsageFilter", "UsageQuery", "UsageQueryPort")
