"""Canonical Activity owner-draft codec."""

from __future__ import annotations

from typing import Any, Protocol, cast
from uuid import UUID

import rfc8785
from armi_kernel.application import CandidateFactClass

from .api import (
    ActivityAttentionDecisionKind,
    ActivityStatus,
    ActivityViolation,
    ActivityWaitingKind,
    CandidateActivityDecisionDraft,
    CandidateActivityDraft,
)


def encode(value: CandidateActivityDraft | CandidateActivityDecisionDraft) -> bytes:
    common: dict[str, object] = {
        "proposal_ref": value.proposal_ref,
        "atomic_group_ref": value.atomic_group_ref,
        "basis_ordinals": list(value.basis_ordinals),
    }
    if type(value) is CandidateActivityDraft:
        document: dict[str, object] = {
            **common,
            "kind": "create",
            "fact_class": value.fact_class.value,
            "activity_id": str(value.activity_id),
            "goal": value.goal,
            "next_safe_step": value.next_safe_step,
            "status": value.status.value,
            "activity_kind": value.activity_kind,
            "privacy_scope": value.privacy_scope,
        }
    elif type(value) is CandidateActivityDecisionDraft:
        document = {
            **common,
            "kind": "decision",
            "activity_id": str(value.activity_id),
            "current_revision_id": str(value.current_revision_id),
            "expected_head_version": value.expected_head_version,
            "decision_kind": value.decision_kind.value,
            "progress_summary": value.progress_summary,
            "next_safe_step": value.next_safe_step,
            "waiting_summary": value.waiting_summary,
            "resumption_cue": value.resumption_cue,
            "waiting_kind": None
            if value.waiting_kind is None
            else value.waiting_kind.value,
            "delay_seconds": value.delay_seconds,
            "terminal_reason": value.terminal_reason,
        }
    else:
        raise ActivityViolation("ACTIVITY-CODEC-TYPE")
    return rfc8785.dumps(cast(Any, document))


def decode(payload: bytes) -> CandidateActivityDraft | CandidateActivityDecisionDraft:
    import json

    try:
        raw = json.loads(payload)
    except UnicodeDecodeError, ValueError, TypeError:
        raise ActivityViolation("ACTIVITY-CODEC-PAYLOAD") from None
    if type(raw) is not dict or rfc8785.dumps(cast(Any, raw)) != payload:
        raise ActivityViolation("ACTIVITY-CODEC-PAYLOAD")
    document = cast(dict[str, object], raw)
    try:
        proposal_ref = str(document["proposal_ref"])
        atomic_group_ref = str(document["atomic_group_ref"])
        basis_ordinals = tuple(cast(list[int], document["basis_ordinals"]))
        fact_class = CandidateFactClass(
            str(document.get("fact_class", "subjective_understanding"))
        )
    except KeyError, TypeError, ValueError:
        raise ActivityViolation("ACTIVITY-CODEC-PAYLOAD") from None
    return _from_mapping(
        document,
        proposal_ref=proposal_ref,
        atomic_group_ref=atomic_group_ref,
        basis_ordinals=basis_ordinals,
        fact_class=fact_class,
    )


class _LegacyActivity(Protocol):
    proposal_ref: str
    atomic_group_ref: str
    basis_ordinals: tuple[int, ...]
    fact_class: object
    activity_id: UUID
    goal: str
    next_safe_step: str
    status: object
    activity_kind: str
    privacy_scope: str
    current_revision_id: UUID
    expected_head_version: int
    decision_kind: object
    progress_summary: str | None
    waiting_summary: str | None
    resumption_cue: str | None
    waiting_kind: object | None
    delay_seconds: int | None
    terminal_reason: str | None


def decode_wire(
    value: object, *, decision: bool
) -> CandidateActivityDraft | CandidateActivityDecisionDraft:
    required = ("proposal_ref", "atomic_group_ref", "basis_ordinals", "activity_id")
    if any(not hasattr(value, name) for name in required):
        raise ActivityViolation("ACTIVITY-CODEC-LEGACY")
    item = cast(_LegacyActivity, value)
    try:
        if decision:
            return CandidateActivityDecisionDraft(
                proposal_ref=item.proposal_ref,
                atomic_group_ref=item.atomic_group_ref,
                basis_ordinals=item.basis_ordinals,
                activity_id=item.activity_id,
                current_revision_id=item.current_revision_id,
                expected_head_version=item.expected_head_version,
                decision_kind=ActivityAttentionDecisionKind(str(item.decision_kind)),
                progress_summary=item.progress_summary,
                next_safe_step=item.next_safe_step,
                waiting_summary=item.waiting_summary,
                resumption_cue=item.resumption_cue,
                waiting_kind=(
                    None
                    if item.waiting_kind is None
                    else ActivityWaitingKind(str(item.waiting_kind))
                ),
                delay_seconds=item.delay_seconds,
                terminal_reason=item.terminal_reason,
            )
        return CandidateActivityDraft(
            proposal_ref=item.proposal_ref,
            atomic_group_ref=item.atomic_group_ref,
            basis_ordinals=item.basis_ordinals,
            fact_class=CandidateFactClass(str(item.fact_class)),
            activity_id=item.activity_id,
            goal=item.goal,
            next_safe_step=item.next_safe_step,
            status=ActivityStatus(str(item.status)),
            activity_kind=item.activity_kind,
            privacy_scope=item.privacy_scope,
        )
    except AttributeError, TypeError, ValueError:
        raise ActivityViolation("ACTIVITY-CODEC-LEGACY") from None


def _from_mapping(
    value: dict[str, Any],
    *,
    proposal_ref: str,
    atomic_group_ref: str,
    basis_ordinals: tuple[int, ...],
    fact_class: CandidateFactClass,
) -> CandidateActivityDraft | CandidateActivityDecisionDraft:
    try:
        if value.get("kind") == "create" and set(value) == {
            "proposal_ref",
            "atomic_group_ref",
            "basis_ordinals",
            "kind",
            "fact_class",
            "activity_id",
            "goal",
            "next_safe_step",
            "status",
            "activity_kind",
            "privacy_scope",
        }:
            return CandidateActivityDraft(
                proposal_ref,
                atomic_group_ref,
                basis_ordinals,
                fact_class,
                UUID(value["activity_id"]),
                value["goal"],
                value["next_safe_step"],
                ActivityStatus(value["status"]),
                value["activity_kind"],
                value["privacy_scope"],
            )
        if value.get("kind") == "decision" and set(value) == {
            "proposal_ref",
            "atomic_group_ref",
            "basis_ordinals",
            "kind",
            "activity_id",
            "current_revision_id",
            "expected_head_version",
            "decision_kind",
            "progress_summary",
            "next_safe_step",
            "waiting_summary",
            "resumption_cue",
            "waiting_kind",
            "delay_seconds",
            "terminal_reason",
        }:
            return CandidateActivityDecisionDraft(
                proposal_ref,
                atomic_group_ref,
                basis_ordinals,
                UUID(value["activity_id"]),
                UUID(value["current_revision_id"]),
                value["expected_head_version"],
                ActivityAttentionDecisionKind(value["decision_kind"]),
                value["progress_summary"],
                value["next_safe_step"],
                value["waiting_summary"],
                value["resumption_cue"],
                None
                if value["waiting_kind"] is None
                else ActivityWaitingKind(value["waiting_kind"]),
                value["delay_seconds"],
                value["terminal_reason"],
            )
    except KeyError, TypeError, ValueError:
        pass
    raise ActivityViolation("ACTIVITY-CODEC-PAYLOAD")


__all__ = ("decode", "decode_wire", "encode")
