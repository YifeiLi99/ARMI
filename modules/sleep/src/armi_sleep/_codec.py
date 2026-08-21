"""Canonical owner payload codec for current sleep drafts."""

from __future__ import annotations

import json
from typing import Any, cast
from uuid import UUID

import rfc8785

from .api import (
    CandidateMaintenanceDecisionDraft,
    CandidateSleepDecisionDraft,
    MaintenancePhase,
    MaintenanceWorkOutcome,
    SleepDecisionKind,
    SleepViolation,
)


def encode(
    value: CandidateSleepDecisionDraft | CandidateMaintenanceDecisionDraft,
) -> bytes:
    common: dict[str, object] = {
        "proposal_ref": value.proposal_ref,
        "atomic_group_ref": value.atomic_group_ref,
        "basis_ordinals": list(value.basis_ordinals),
    }
    if isinstance(value, CandidateSleepDecisionDraft):
        common.update(
            operation="decide",
            decision_kind=value.decision_kind.value,
            cycle_anchor_ref=str(value.cycle_anchor_ref),
        )
    else:
        common.update(
            operation="record_maintenance",
            maintenance_session_id=str(value.maintenance_session_id),
            current_revision_id=str(value.current_revision_id),
            expected_head_version=value.expected_head_version,
            phase=value.phase.value,
            outcome=value.outcome.value,
            result_summary=value.result_summary,
            creator_visible_problem=value.creator_visible_problem,
            memory_proposal_ref=value.memory_proposal_ref,
            issue_target=value.issue_target,
        )
    return rfc8785.dumps(cast(Any, common))


def decode(
    payload: bytes,
) -> CandidateSleepDecisionDraft | CandidateMaintenanceDecisionDraft:
    try:
        value = json.loads(payload)
        if type(value) is not dict or rfc8785.dumps(cast(Any, value)) != payload:
            raise ValueError
        return _decode_mapping(cast(dict[str, object], value))
    except KeyError, TypeError, ValueError, SleepViolation:
        raise SleepViolation("SLEEP-CODEC") from None


def _decode_mapping(
    item: dict[str, object],
) -> CandidateSleepDecisionDraft | CandidateMaintenanceDecisionDraft:
    proposal_ref = str(item["proposal_ref"])
    atomic_group_ref = str(item["atomic_group_ref"])
    basis_ordinals = tuple(cast(list[int], item["basis_ordinals"]))
    if item["operation"] == "decide":
        return CandidateSleepDecisionDraft(
            proposal_ref,
            atomic_group_ref,
            basis_ordinals,
            SleepDecisionKind(str(item["decision_kind"])),
            UUID(str(item["cycle_anchor_ref"])),
        )
    return CandidateMaintenanceDecisionDraft(
        proposal_ref,
        atomic_group_ref,
        basis_ordinals,
        UUID(str(item["maintenance_session_id"])),
        UUID(str(item["current_revision_id"])),
        cast(int, item["expected_head_version"]),
        MaintenancePhase(str(item["phase"])),
        MaintenanceWorkOutcome(str(item["outcome"])),
        str(item["result_summary"]),
        (
            None
            if item["creator_visible_problem"] is None
            else str(item["creator_visible_problem"])
        ),
        (
            None
            if item["memory_proposal_ref"] is None
            else str(item["memory_proposal_ref"])
        ),
        None if item.get("issue_target") is None else str(item["issue_target"]),
    )


__all__ = ("decode", "encode")
