from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid7

import pytest
from armi_kernel.contracts import Instant
from armi_material.api import (
    CreatorLifeMaterialItem,
    LifeMaterialKind,
    LifeMaterialPrivacyStatus,
    LifeMaterialStatus,
    MaterialViolation,
)


def item(**changes: object) -> CreatorLifeMaterialItem:
    body = "一段当前可见正文"
    values: dict[str, object] = {
        "material_id": uuid7(),
        "current_revision_id": uuid7(),
        "material_kind": LifeMaterialKind.DIARY,
        "revision_no": 2,
        "head_version": 2,
        "title": "雨天随记",
        "body": body,
        "metadata": (("mood", "quiet"),),
        "material_status": LifeMaterialStatus.ACTIVE,
        "privacy_status": LifeMaterialPrivacyStatus.CREATOR_VISIBLE,
        "created_at": Instant(datetime(2026, 8, 5, 9, 0, tzinfo=UTC)),
        "updated_at": Instant(datetime(2026, 8, 5, 10, 0, tzinfo=UTC)),
    }
    values.update(changes)
    return CreatorLifeMaterialItem(**values)  # pyright: ignore[reportArgumentType]


def test_creator_material_contract_accepts_only_current_visible_content() -> None:
    visible = item()
    assert visible.privacy_status is LifeMaterialPrivacyStatus.CREATOR_VISIBLE
    with pytest.raises(ValueError):
        item(privacy_status=LifeMaterialPrivacyStatus.PRIVATE)
    with pytest.raises(ValueError):
        item(updated_at=Instant(datetime(2026, 8, 5, 8, 0, tzinfo=UTC)))


def test_creator_material_query_codes_are_narrow() -> None:
    error = MaterialViolation("MATERIAL-QUERY-UNAVAILABLE")
    assert error.code == "MATERIAL-QUERY-UNAVAILABLE"
    with pytest.raises(ValueError):
        MaterialViolation("LIFE-QUERY-UNAVAILABLE")
