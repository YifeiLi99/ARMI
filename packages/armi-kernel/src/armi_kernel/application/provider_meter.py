"""Task-scoped provider receipts, written through the calling owner's sink.

The scope contains no global persistence and is never an optional telemetry hook:
an external adapter cannot dispatch without a bound durable sink.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable, Generator, Mapping
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from typing import Literal, cast
from uuid import uuid7

from .provider_usage import (
    CostEstimate,
    PriceCatalog,
    PriceSnapshot,
    UsageQuantity,
    UsageSource,
    UsageUnit,
    estimate_cost,
)

CallOutcome = Literal["pending", "returned", "failed", "unknown"]
type SafeUsage = dict[str, int | SafeUsage | None]
_MODEL_UNITS = (
    UsageUnit.INPUT_TOKENS,
    UsageUnit.CACHED_INPUT_TOKENS,
    UsageUnit.OUTPUT_TOKENS,
)
_UNITS = {
    "generation": _MODEL_UNITS,
    "web_search": (*_MODEL_UNITS, UsageUnit.WEB_SEARCH_CALLS),
    "asr": (UsageUnit.AUDIO_MILLISECONDS,),
    "tts": (UsageUnit.TEXT_CHARACTERS,),
    "tokenization": (),
    "poll": (),
}


@dataclass(frozen=True, slots=True)
class ProviderCallReceipt:
    call_id: str
    provider: str
    model: str
    service: str
    purpose: str
    started_at: str
    price: PriceSnapshot | None
    cost: CostEstimate
    billable: bool
    outcome: CallOutcome = "pending"
    provider_request_id: str | None = None
    response_model: str | None = None
    quantities: tuple[UsageQuantity, ...] = ()
    raw_usage: SafeUsage | None = None
    received_at: str | None = None
    finished_at: str | None = None
    error_code: str | None = None
    parent_call_id: str | None = None
    schema_version: str = "armi.provider-call.v1"

    @property
    def registration(self) -> bool:
        return self.received_at is None and self.finished_at is None

    def document(self) -> dict[str, object]:
        result = asdict(self)
        # Datetimes in price snapshots use the same explicit UTC wire convention.
        if self.price is not None:
            result["price"] = {
                **asdict(self.price),
                "effective_from": self.price.effective_from.isoformat(),
                "effective_until": (
                    None
                    if self.price.effective_until is None
                    else self.price.effective_until.isoformat()
                ),
                "verified_at": self.price.verified_at.isoformat(),
            }
        return result


ReceiptWriter = Callable[[ProviderCallReceipt], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class ProviderMeterScope:
    write: ReceiptWriter
    prices: PriceCatalog
    purpose: str


_SCOPE: ContextVar[ProviderMeterScope] = ContextVar("armi_provider_meter")


@contextmanager
def provider_meter_scope(scope: ProviderMeterScope) -> Generator[None]:
    token = _SCOPE.set(scope)
    try:
        yield
    finally:
        _SCOPE.reset(token)


class MeteredProviderCall:
    def __init__(self, receipt: ProviderCallReceipt, write: ReceiptWriter) -> None:
        self.receipt = receipt
        self._write = write
        self._lock = asyncio.Lock()

    async def capture(
        self,
        *,
        usage: Mapping[str, object] | None,
        provider_request_id: str | None = None,
        response_model: str | None = None,
        quantities: tuple[UsageQuantity, ...] | None = None,
    ) -> None:
        async with self._lock:
            await self._capture(
                usage=usage,
                provider_request_id=provider_request_id,
                response_model=response_model,
                quantities=quantities,
            )

    async def _capture(
        self,
        *,
        usage: Mapping[str, object] | None,
        provider_request_id: str | None = None,
        response_model: str | None = None,
        quantities: tuple[UsageQuantity, ...] | None = None,
    ) -> None:
        """Persist a cumulative receipt before consumers inspect business output."""
        measured = normalize_token_usage(usage) if quantities is None else quantities
        # No partial/terminal observation may erase previously received dimensions.
        merged = {item.unit: item for item in self.receipt.quantities}
        for item in measured:
            previous = merged.get(item.unit)
            if (
                previous is None
                or previous.source is not UsageSource.PROVIDER
                or item.source is UsageSource.PROVIDER
            ):
                merged[item.unit] = item
        observed = tuple(merged.values())
        pricing_error: ValueError | None = None
        try:
            cost = estimate_cost(
                quantities=observed,
                required_units=_UNITS[self.receipt.service],
                snapshot=self.receipt.price,
                billable=self.receipt.billable,
            )
        except ValueError as error:
            # Invalid supplier quantities are still a received fact. Persist them
            # before rejecting the response; do not replace them with zero usage.
            pricing_error = error
            cost = estimate_cost(
                quantities=(),
                required_units=_UNITS[self.receipt.service],
                snapshot=self.receipt.price,
                billable=self.receipt.billable,
            )
        updated = replace(
            self.receipt,
            quantities=observed,
            raw_usage=self.receipt.raw_usage if usage is None else safe_usage(usage),
            received_at=datetime.now(UTC).isoformat(),
            provider_request_id=provider_request_id or self.receipt.provider_request_id,
            response_model=response_model or self.receipt.response_model,
            cost=cost,
            error_code=None if pricing_error is None else "USAGE-INVALID-QUANTITIES",
        )
        await self._write(updated)
        self.receipt = updated
        if pricing_error is not None:
            raise pricing_error

    async def finish(
        self, outcome: CallOutcome, *, error_code: str | None = None
    ) -> None:
        async with self._lock:
            await self._finish(outcome, error_code=error_code)

    async def _finish(
        self, outcome: CallOutcome, *, error_code: str | None = None
    ) -> None:
        updated = replace(
            self.receipt,
            outcome=outcome,
            error_code=self.receipt.error_code or error_code,
            finished_at=datetime.now(UTC).isoformat(),
        )
        await self._write(updated)
        self.receipt = updated


@asynccontextmanager
async def provider_call(
    *,
    provider: str,
    model: str,
    service: str,
    parent_call_id: str | None = None,
) -> AsyncGenerator[MeteredProviderCall]:
    try:
        scope = _SCOPE.get()
    except LookupError:
        raise RuntimeError("USAGE-DURABLE-SINK-REQUIRED") from None
    units = _UNITS[service]
    now = datetime.now(UTC)
    snapshot = scope.prices.select(
        provider=provider, model=model, service=service, at=now
    )
    billable = service not in {"tokenization", "poll"}
    receipt = ProviderCallReceipt(
        str(uuid7()),
        provider,
        model,
        service,
        scope.purpose,
        now.isoformat(),
        snapshot,
        estimate_cost(
            quantities=(), required_units=units, snapshot=snapshot, billable=billable
        ),
        billable,
        parent_call_id=parent_call_id,
    )
    # Commit before yielding control to the adapter: failure means no request.
    await scope.write(receipt)
    call = MeteredProviderCall(receipt, scope.write)
    try:
        yield call
    except BaseException as error:
        # A returned receipt remains useful even when cancellation or parsing fails.
        if call.receipt.outcome == "pending":
            status = getattr(error, "status_code", None)
            if type(status) is int and 400 <= status < 600:
                await call.finish("failed", error_code=f"USAGE-PROVIDER-HTTP-{status}")
            else:
                await call.finish(
                    "unknown",
                    error_code="USAGE-CALL-TIMEOUT"
                    if isinstance(error, TimeoutError)
                    else "USAGE-CALL-INTERRUPTED",
                )
        raise
    else:
        if call.receipt.outcome == "pending":
            await call.finish("returned")


def normalize_token_usage(
    usage: Mapping[str, object] | None,
) -> tuple[UsageQuantity, ...]:
    if usage is None:
        return ()
    values: dict[UsageUnit, int] = {}
    for unit in _MODEL_UNITS:
        value = usage.get(unit.value)
        if type(value) is int and value >= 0:
            values[unit] = value
    details = usage.get("input_tokens_details")
    if isinstance(details, Mapping):
        cached = cast(Mapping[str, object], details).get("cached_tokens")
        if type(cached) is int and cached >= 0:
            values[UsageUnit.CACHED_INPUT_TOKENS] = cached
    tool = usage.get("tool_usage")
    if isinstance(tool, Mapping):
        searches = cast(Mapping[str, object], tool).get("web_search")
        if type(searches) is int and searches >= 0:
            values[UsageUnit.WEB_SEARCH_CALLS] = searches
    return tuple(
        UsageQuantity(unit, value, UsageSource.PROVIDER)
        for unit, value in values.items()
    )


def safe_usage(value: Mapping[str, object]) -> SafeUsage:
    """Copy only metering scalars; provider bodies and arbitrary strings stay out."""
    result: SafeUsage = {}
    for key, item in value.items():
        if not key.replace("_", "").isalnum() or len(key) > 96:
            continue
        if type(item) is int or item is None:
            result[key] = item
        elif isinstance(item, Mapping):
            result[key] = safe_usage(cast(Mapping[str, object], item))
    return result


__all__ = (
    "MeteredProviderCall",
    "ProviderCallReceipt",
    "ProviderMeterScope",
    "ReceiptWriter",
    "normalize_token_usage",
    "provider_call",
    "provider_meter_scope",
)
