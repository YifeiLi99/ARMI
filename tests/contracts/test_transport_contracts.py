"""CON-TRANSPORT conformance for the frozen public transport v1 surface."""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import cast
from uuid import UUID

import pytest
from armi_kernel.contracts import (
    CONTRACT_VERSION,
    AcceptedOutcome,
    AppliedOutcome,
    CompletedOutcome,
    ContractViolation,
    Digest,
    ErrorCategory,
    ErrorDescriptor,
    FailedOutcome,
    IdempotencyKey,
    Instant,
    OpaqueCursor,
    Page,
    PageRequest,
    Purpose,
    RejectedOutcome,
    SubjectId,
    TraceId,
    UnavailableOutcome,
    UnknownOutcome,
    WaitingOutcome,
)
from hypothesis import given
from hypothesis import strategies as st

VECTOR_PATH = Path(__file__).parent / "fixtures/transport-v1.json"
VECTOR = cast(dict[str, object], json.loads(VECTOR_PATH.read_text(encoding="utf-8")))
VALID = cast(dict[str, object], VECTOR["valid"])

OUTCOME_DECODERS = {
    "accepted": AcceptedOutcome.from_wire,
    "applied": AppliedOutcome.from_wire,
    "waiting": WaitingOutcome.from_wire,
    "rejected": RejectedOutcome.from_wire,
    "unavailable": UnavailableOutcome.from_wire,
    "failed": FailedOutcome.from_wire,
    "unknown": UnknownOutcome.from_wire,
    "completed": CompletedOutcome.from_wire,
}


def _assert_code(expected: str, action) -> None:
    with pytest.raises(ContractViolation) as raised:
        action()
    assert raised.value.code == expected


def _reject_invalid(kind: object, value: object) -> object:
    if kind == "contract_version":
        wire = copy.deepcopy(cast(dict[str, object], VALID["page_request"]))
        wire["contract_version"] = value
        return PageRequest.from_wire(wire)
    if kind == "uuid":
        return SubjectId.from_wire(value)
    if kind == "trace_id":
        return TraceId.from_wire(value)
    if kind == "digest":
        return Digest.from_wire(value)
    if kind == "instant":
        return Instant.from_wire(value)
    if kind == "outcome_status":
        wire = copy.deepcopy(cast(list[dict[str, object]], VALID["outcomes"])[0])
        wire["status"] = value
        return AcceptedOutcome.from_wire(wire)
    if kind == "cursor":
        return OpaqueCursor.from_wire(value)
    return PageRequest.from_wire({"contract_version": CONTRACT_VERSION, "limit": value})


def test_contract_version_and_public_values_round_trip() -> None:
    assert CONTRACT_VERSION == "1.0"
    assert Digest.from_bytes(b"ARMI").to_wire().startswith("sha256:")
    assert IdempotencyKey.from_wire("retry:0001").to_wire() == "retry:0001"
    assert Purpose.from_wire("birth.acceptance").to_wire() == "birth.acceptance"


def test_all_eight_outcome_variants_round_trip_exactly() -> None:
    outcome_wires = cast(list[dict[str, object]], VALID["outcomes"])
    assert set(OUTCOME_DECODERS) == {
        "accepted",
        "applied",
        "waiting",
        "rejected",
        "unavailable",
        "failed",
        "unknown",
        "completed",
    }
    for wire in outcome_wires:
        status = cast(str, wire["status"])
        outcome = OUTCOME_DECODERS[status](wire)
        assert outcome.to_wire() == wire


def test_pagination_and_item_decoder_round_trip() -> None:
    request_wire = cast(dict[str, object], VALID["page_request"])
    request = PageRequest.from_wire(request_wire)
    assert request.to_wire() == request_wire

    page_wire = cast(dict[str, object], VALID["page"])
    page = Page.from_wire(page_wire, item_decoder=lambda item: cast(object, item))
    assert page.to_wire(item_encoder=lambda item: item) == page_wire


def test_error_category_requires_matching_code_prefix() -> None:
    error = ErrorDescriptor.from_wire(
        {
            "category": "input",
            "code": "INPUT_SCHEMA_UNSUPPORTED",
            "details": {"field": "payload"},
        }
    )
    assert error.category is ErrorCategory.INPUT
    assert error.to_wire()["details"] == {"field": "payload"}
    _assert_code(
        "CON-ERROR",
        lambda: ErrorDescriptor.from_wire(
            {"category": "input", "code": "AUTH_INVALID_TOKEN"}
        ),
    )


def test_shared_invalid_vectors_have_stable_rejection_codes() -> None:
    invalid = cast(list[dict[str, object]], VECTOR["invalid"])
    for vector in invalid:
        kind = vector["kind"]
        value = vector["value"]
        expected = cast(str, vector["expected_code"])
        _assert_code(
            expected,
            lambda kind=kind, value=value: _reject_invalid(kind, value),
        )


def test_unknown_missing_and_variant_fields_are_rejected() -> None:
    page = copy.deepcopy(cast(dict[str, object], VALID["page_request"]))
    page["extra"] = True
    _assert_code(
        "CON-FIELD-UNKNOWN",
        lambda: PageRequest.from_wire(page),
    )
    del page["extra"]
    del page["limit"]
    _assert_code(
        "CON-FIELD-MISSING",
        lambda: PageRequest.from_wire(page),
    )

    accepted = copy.deepcopy(cast(list[dict[str, object]], VALID["outcomes"])[0])
    accepted["retryable"] = False
    _assert_code("CON-FIELD-UNKNOWN", lambda: AcceptedOutcome.from_wire(accepted))


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("018F3F7D-8B2A-7C4D-8E9F-0123456789AB", "CON-ID"),
        ("123e4567-e89b-42d3-a456-426614174000", "CON-ID"),
        ("F123456789abcdef0123456789abcdef", "CON-TRACE"),
        ("0" * 32, "CON-TRACE"),
        ("sha256:" + "A" * 64, "CON-DIGEST"),
        ("2026-07-29T08:00:00-00:00", "CON-TIME"),
        ("2026-07-29T08:00:60Z", "CON-TIME"),
        ("2026-07-29T08:00:00.0000001Z", "CON-TIME"),
    ],
)
def test_noncanonical_scalars_are_rejected(value: str, expected: str) -> None:
    decoder = (
        SubjectId.from_wire
        if expected == "CON-ID"
        else TraceId.from_wire
        if expected == "CON-TRACE"
        else Digest.from_wire
        if expected == "CON-DIGEST"
        else Instant.from_wire
    )
    _assert_code(expected, lambda: decoder(value))


@pytest.mark.parametrize("limit", [True, 0, 101, 1.0])
def test_invalid_page_limits_are_rejected(limit: object) -> None:
    _assert_code(
        "CON-PAGE",
        lambda: PageRequest.from_wire(
            {"contract_version": CONTRACT_VERSION, "limit": limit}
        ),
    )


@pytest.mark.parametrize(
    "details",
    [
        {"value": float("nan")},
        {"value": float("inf")},
        {"value": 9_007_199_254_740_992},
        {"value": b"not-json"},
        {"value": datetime.now(UTC)},
    ],
)
def test_unsafe_error_details_are_rejected(details: object) -> None:
    _assert_code(
        "CON-JSON",
        lambda: ErrorDescriptor.from_wire(
            {"category": "input", "code": "INPUT_INVALID", "details": details}
        ),
    )


def test_excessive_json_depth_is_rejected() -> None:
    value: object = "leaf"
    for _ in range(10):
        value = {"nested": value}
    _assert_code(
        "CON-JSON",
        lambda: ErrorDescriptor.from_wire(
            {"category": "input", "code": "INPUT_INVALID", "details": value}
        ),
    )


@given(st.integers(min_value=0, max_value=(1 << 128) - 1))
def test_uuidv7_property_round_trip(value: int) -> None:
    canonical_int = value & ~(0xF << 76) | (7 << 76)
    canonical_int = canonical_int & ~(0b11 << 62) | (0b10 << 62)
    uuid_value = UUID(int=canonical_int)
    assert SubjectId.from_wire(str(uuid_value)).value == uuid_value


@given(st.binary(max_size=2048))
def test_digest_property_is_canonical(value: bytes) -> None:
    digest = Digest.from_bytes(value)
    assert Digest.from_wire(digest.to_wire()) == digest


@given(st.integers(min_value=1, max_value=100))
def test_page_limit_property_round_trip(limit: int) -> None:
    assert PageRequest.from_wire(PageRequest(limit).to_wire()).limit == limit


@given(
    st.datetimes(
        min_value=datetime(2000, 1, 1),
        max_value=datetime(2099, 12, 31, 23, 59, 59, 999999),
    ),
    st.integers(min_value=-720, max_value=840).filter(lambda value: value != 0),
)
def test_instant_property_normalizes_offsets(
    local: datetime, offset_minutes: int
) -> None:
    aware = local.replace(tzinfo=timezone(timedelta(minutes=offset_minutes)))
    wire = aware.isoformat(timespec="microseconds")
    parsed = Instant.from_wire(wire)
    assert parsed.value == aware.astimezone(UTC)
    assert parsed.to_wire().endswith("Z")
