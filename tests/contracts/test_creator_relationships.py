"""Creator relationship projection contract tests."""

from __future__ import annotations

from dataclasses import fields
from datetime import UTC, datetime
from uuid import uuid7

import pytest
from armi_relationship.api import (
    CreatorRelationshipItem,
    CreatorRelationshipRevision,
    CreatorRelationshipTimeline,
    RelationshipBoundary,
    RelationshipBoundaryAction,
    RelationshipBoundaryKind,
    RelationshipFact,
    RelationshipFactKind,
    RelationshipPartyRole,
    RelationshipStatus,
)
from armi_relationship.api import (
    RelationshipViolation as CreatorRelationshipViolation,
)


def revision(*, revision_no: int = 1) -> CreatorRelationshipRevision:
    return CreatorRelationshipRevision(
        relationship_revision_id=uuid7(),
        revision_no=revision_no,
        facts=(
            RelationshipFact(
                uuid7(),
                RelationshipFactKind.PARTY_EXPRESSION,
                "Creator 表达了联系限制",
            ),
        ),
        interpretation="我会尊重这项边界",
        boundaries=(
            RelationshipBoundary(
                RelationshipPartyRole.OTHER,
                RelationshipBoundaryKind.CONTACT,
                RelationshipBoundaryAction.RESTRICT,
                "不要在深夜联系",
            ),
        ),
        commitments=(),
        open_issues=(),
        commitment_event=None,
        status=RelationshipStatus.ACTIVE,
        occurred_at=datetime(2026, 8, 5, 10, 0, tzinfo=UTC),
    )


def test_projection_contains_only_structured_relationship_summary() -> None:
    current = revision()
    field_names = {field.name for field in fields(current)}
    assert "scene_key" not in field_names
    assert "message" not in field_names
    assert current.boundaries[0].party_role is RelationshipPartyRole.OTHER
    relationship = CreatorRelationshipItem(
        relationship_id=uuid7(),
        current_revision_id=current.relationship_revision_id,
        head_version=1,
        current=current,
        created_at=current.occurred_at,
    )
    assert relationship.current.interpretation == "我会尊重这项边界"


def test_projection_head_and_timeline_are_server_owned() -> None:
    current = revision(revision_no=2)
    with pytest.raises(CreatorRelationshipViolation, match="RELATIONSHIP-QUERY-ITEM"):
        CreatorRelationshipItem(
            relationship_id=uuid7(),
            current_revision_id=current.relationship_revision_id,
            head_version=1,
            current=current,
            created_at=current.occurred_at,
        )
    assert CreatorRelationshipTimeline(uuid7(), (current,), False).items == (current,)
    with pytest.raises(
        CreatorRelationshipViolation,
        match="RELATIONSHIP-QUERY-TIMELINE",
    ):
        CreatorRelationshipTimeline(
            uuid7(),
            tuple(revision() for _ in range(101)),
            True,
        )
