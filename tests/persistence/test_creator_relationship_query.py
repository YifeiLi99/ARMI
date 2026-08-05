"""Relationship projection persistence-shape checks."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid7

import pytest
from armi_kernel.application import CreatorRelationshipViolation
from armi_runtime.adapters.persistence.creator_relationships import _revision


def row(*, facts: object) -> tuple[object, ...]:
    return (
        uuid7(),
        1,
        facts,
        "我会尊重这项边界",
        [
            {
                "party_role": "other",
                "kind": "contact",
                "action": "restrict",
                "summary": "不要在深夜联系",
            }
        ],
        [],
        [],
        None,
        "active",
        datetime(2026, 8, 5, 10, 0, tzinfo=UTC),
    )


def test_parser_accepts_only_the_structured_revision_shape() -> None:
    parsed = _revision(
        row(
            facts=[
                {
                    "kind": "party_expression",
                    "summary": "Creator 表达了联系限制",
                }
            ]
        )
    )
    assert parsed.facts[0].summary == "Creator 表达了联系限制"


def test_parser_rejects_scene_or_message_fields() -> None:
    with pytest.raises(CreatorRelationshipViolation, match="RELATIONSHIP-QUERY-SHAPE"):
        _revision(
            row(
                facts=[
                    {
                        "kind": "party_expression",
                        "summary": "Creator 表达了联系限制",
                        "scene_text": "不应进入关系投影",
                    }
                ]
            )
        )
