from __future__ import annotations

from uuid import uuid7

import pytest
from armi_relationship._domain import apply_boundary_operations, apply_fact_operations
from armi_relationship._model_contract import RelationshipChangeV22
from armi_relationship.api import (
    RelationshipBoundary,
    RelationshipBoundaryAction,
    RelationshipBoundaryKind,
    RelationshipBoundaryOperation,
    RelationshipBoundaryOperationKind,
    RelationshipFact,
    RelationshipFactKind,
    RelationshipFactOperation,
    RelationshipFactOperationKind,
    RelationshipPartyRole,
    RelationshipViolation,
)
from pydantic import ValidationError


def _fact(summary: str) -> RelationshipFact:
    return RelationshipFact(uuid7(), RelationshipFactKind.PARTY_EXPRESSION, summary)


def test_fact_operations_add_revise_remove_and_reject_invalid_reference() -> None:
    first = _fact("初始事实")
    added = _fact("新增事实")
    current = (first,)
    result = apply_fact_operations(
        current,
        (RelationshipFactOperation(RelationshipFactOperationKind.ADD, None, added),),
        allowed_context_refs=frozenset(),
    )
    revised = RelationshipFact(first.fact_id, first.kind, "修订事实")
    result = apply_fact_operations(
        result,
        (
            RelationshipFactOperation(
                RelationshipFactOperationKind.REVISE,
                first.fact_id,
                revised,
                "ctx:1",
            ),
        ),
        allowed_context_refs=frozenset({"ctx:1"}),
    )
    result = apply_fact_operations(
        result,
        (
            RelationshipFactOperation(
                RelationshipFactOperationKind.REMOVE,
                added.fact_id,
                None,
                "ctx:2",
            ),
        ),
        allowed_context_refs=frozenset({"ctx:2"}),
    )
    assert result == (revised,)
    with pytest.raises(RelationshipViolation, match="RELATIONSHIP-FACT-REFERENCE"):
        apply_fact_operations(
            result,
            (
                RelationshipFactOperation(
                    RelationshipFactOperationKind.REMOVE,
                    revised.fact_id,
                    None,
                    "ctx:missing",
                ),
            ),
            allowed_context_refs=frozenset(),
        )


def test_last_fact_and_no_change_are_rejected() -> None:
    fact = _fact("唯一事实")
    with pytest.raises(RelationshipViolation, match="RELATIONSHIP-LAST-FACT"):
        apply_fact_operations(
            (fact,),
            (
                RelationshipFactOperation(
                    RelationshipFactOperationKind.REMOVE,
                    fact.fact_id,
                    None,
                    "ctx:1",
                ),
            ),
            allowed_context_refs=frozenset({"ctx:1"}),
        )
    with pytest.raises(RelationshipViolation, match="RELATIONSHIP-NO-CHANGE"):
        apply_fact_operations(
            (fact,),
            (
                RelationshipFactOperation(
                    RelationshipFactOperationKind.REVISE,
                    fact.fact_id,
                    fact,
                    "ctx:1",
                ),
            ),
            allowed_context_refs=frozenset({"ctx:1"}),
        )


def test_boundary_slots_are_set_and_removed_explicitly() -> None:
    boundary = RelationshipBoundary(
        RelationshipPartyRole.SUBJECT,
        RelationshipBoundaryKind.CONTACT,
        RelationshipBoundaryAction.RESTRICT,
        "仅在必要时联系",
    )
    set_operation = RelationshipBoundaryOperation(
        RelationshipBoundaryOperationKind.SET,
        boundary.party_role,
        boundary.kind,
        boundary,
    )
    assert apply_boundary_operations((), (set_operation,)) == (boundary,)
    remove_operation = RelationshipBoundaryOperation(
        RelationshipBoundaryOperationKind.REMOVE,
        boundary.party_role,
        boundary.kind,
    )
    assert apply_boundary_operations((boundary,), (remove_operation,)) == ()


def test_active_v22_model_contract_uses_explicit_operations_and_references() -> None:
    value = RelationshipChangeV22.model_validate(
        {
            "facts": [
                {
                    "operation": "revise",
                    "fact_id": str(uuid7()),
                    "context_ref": "ctx:2",
                    "kind": "party_expression",
                    "summary": "对方重新说明了自己的边界。",
                }
            ],
            "boundaries": [
                {
                    "operation": "remove",
                    "party": "other",
                    "kind": "contact",
                }
            ],
            "interpretation": "我更新了对这段关系的理解。",
            "issue_resolution": {
                "issue_ref": "ctx:3",
                "resolution_summary": "双方已经明确消除了原来的冲突。",
            },
        }
    )
    assert value.facts[0].operation == "revise"
    assert value.boundaries[0].operation == "remove"

    with pytest.raises(ValidationError):
        RelationshipChangeV22.model_validate(
            {
                "facts": [
                    {
                        "operation": "remove",
                        "fact_id": str(uuid7()),
                        "context_ref": "not-a-context-ref",
                    }
                ],
                "boundaries": [],
                "interpretation": "无效引用不能进入候选。",
            }
        )
