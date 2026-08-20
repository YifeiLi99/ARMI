from __future__ import annotations

import pytest
from armi_effect._dispatch import (
    _AbsentDisposition,
    _classify_absent_effect,
)


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({}, _AbsentDisposition.RETRY),
        ({"attempt_count": 2}, _AbsentDisposition.FAILED),
        (
            {"grant_status": "revoked"},
            _AbsentDisposition.CANCELLED_REVOKED,
        ),
        (
            {"grant_status": "expired", "grant_time_valid": False},
            _AbsentDisposition.CANCELLED_EXPIRED,
        ),
        (
            {"before_dispatch_deadline": False},
            _AbsentDisposition.CANCELLED_EXPIRED,
        ),
        (
            {"policy_current": False},
            _AbsentDisposition.CANCELLED_SUPERSEDED,
        ),
    ],
)
def test_confirmed_absent_attempt_only_retries_under_current_grant(
    overrides: dict[str, object], expected: _AbsentDisposition
) -> None:
    values: dict[str, object] = {
        "attempt_count": 1,
        "max_attempts": 2,
        "before_dispatch_deadline": True,
        "policy_current": True,
        "grant_status": "active",
        "grant_time_valid": True,
    }
    values.update(overrides)

    assert _classify_absent_effect(**values) is expected  # type: ignore[arg-type]
