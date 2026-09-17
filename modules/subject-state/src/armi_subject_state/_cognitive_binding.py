"""Bind psychological change references within the owning domain."""

from typing import Any
from uuid import UUID

from armi_kernel.application import CandidateBasis

from ._concerns import ActivityReview, ConcernChange, CreateConcern


def bind_concern_changes(
    changes: tuple[ConcernChange, ...],
    *,
    basis_by_ref: dict[str, CandidateBasis],
    current_activity_id: UUID | None,
) -> tuple[
    tuple[ConcernChange, ...] | None, tuple[int, ...], str | None, tuple[str, ...]
]:
    ordinals: set[int] = set()
    bound: list[ConcernChange] = []
    for change in changes:
        updates: dict[str, Any] = {}
        for ref in change.basis_refs:
            basis = basis_by_ref.get(ref)
            if basis is None:
                return (
                    None,
                    (),
                    "CANDIDATE-CONCERN-BASIS",
                    ("concern_changes", "basis_refs"),
                )
            ordinals.add(basis.ordinal)
        if not isinstance(change, CreateConcern):
            basis = basis_by_ref.get(change.concern_ref)
            if (
                basis is None
                or basis.item_kind != "current_concern"
                or basis.source_ref is None
            ):
                return (
                    None,
                    (),
                    "CANDIDATE-CONCERN-REFERENCE",
                    ("concern_changes", "concern_ref"),
                )
            updates["concern_ref"] = str(basis.source_ref)
            ordinals.add(basis.ordinal)
        review = getattr(change, "review", None)
        if isinstance(review, ActivityReview):
            basis = basis_by_ref.get(review.activity_ref)
            if (
                basis is None
                or basis.item_kind != "current_activity"
                or current_activity_id is None
            ):
                return (
                    None,
                    (),
                    "CANDIDATE-CONCERN-ACTIVITY",
                    ("concern_changes", "review"),
                )
            updates["review"] = review.model_copy(
                update={"activity_ref": str(current_activity_id)}
            )
            ordinals.add(basis.ordinal)
        bound.append(change.model_copy(update=updates))
    return tuple(bound), tuple(sorted(ordinals)), None, ()
