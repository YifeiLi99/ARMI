"""Pure relationship lifecycle transitions."""

from __future__ import annotations

from .api import (
    RelationshipBoundary,
    RelationshipBoundaryOperation,
    RelationshipBoundaryOperationKind,
    RelationshipFact,
    RelationshipFactOperation,
    RelationshipFactOperationKind,
    RelationshipViolation,
)


def apply_boundary_operations(
    current: tuple[RelationshipBoundary, ...],
    operations: tuple[RelationshipBoundaryOperation, ...],
) -> tuple[RelationshipBoundary, ...]:
    values = {(item.party_role, item.kind): item for item in current}
    for operation in operations:
        slot = (operation.party_role, operation.boundary_kind)
        if operation.kind is RelationshipBoundaryOperationKind.SET:
            assert operation.boundary is not None
            if values.get(slot) == operation.boundary:
                raise RelationshipViolation("RELATIONSHIP-NO-CHANGE")
            values[slot] = operation.boundary
        else:
            if slot not in values:
                raise RelationshipViolation("RELATIONSHIP-BOUNDARY-REFERENCE")
            del values[slot]
    result = tuple(values.values())
    if result == current:
        raise RelationshipViolation("RELATIONSHIP-NO-CHANGE")
    return result


def apply_fact_operations(
    current: tuple[RelationshipFact, ...],
    operations: tuple[RelationshipFactOperation, ...],
    *,
    allowed_context_refs: frozenset[str],
) -> tuple[RelationshipFact, ...]:
    values = {item.fact_id: item for item in current}
    for operation in operations:
        if operation.kind is RelationshipFactOperationKind.ADD:
            fact = operation.fact
            assert fact is not None
            if fact.fact_id in values:
                raise RelationshipViolation("RELATIONSHIP-FACT-DUPLICATE")
            values[fact.fact_id] = fact
            continue
        if (
            operation.context_ref not in allowed_context_refs
            or operation.fact_id not in values
        ):
            raise RelationshipViolation("RELATIONSHIP-FACT-REFERENCE")
        fact_id = operation.fact_id
        assert fact_id is not None
        if operation.kind is RelationshipFactOperationKind.REVISE:
            fact = operation.fact
            assert fact is not None
            if values[fact_id] == fact:
                raise RelationshipViolation("RELATIONSHIP-NO-CHANGE")
            values[fact_id] = fact
        else:
            if len(values) == 1:
                raise RelationshipViolation("RELATIONSHIP-LAST-FACT")
            del values[fact_id]
    result = tuple(values.values())
    if result == current:
        raise RelationshipViolation("RELATIONSHIP-NO-CHANGE")
    return result


__all__ = ("apply_boundary_operations", "apply_fact_operations")
