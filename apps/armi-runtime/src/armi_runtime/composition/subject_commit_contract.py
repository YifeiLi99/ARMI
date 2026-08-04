"""Strict parser for the persisted T-03 input artifact."""

from __future__ import annotations

import json
from typing import Any, cast
from uuid import UUID

import rfc8785
from armi_kernel.application import (
    ActivityAttentionDecisionKind,
    ActivityStatus,
    ActivityWaitingKind,
    CandidateActivityDecisionDraft,
    CandidateActivityDraft,
    CandidateComponentDraft,
    CandidateDisposition,
    CandidateExperienceDraft,
    CandidateFactClass,
    CandidateOwner,
    CandidateRejection,
    CandidateSleepDecisionDraft,
    CandidateViolation,
    CapabilityKind,
    CapabilityOperation,
    CapabilityRequestDraft,
    CodexDelegatedWorkScope,
    CodexDelegationDraft,
    CodexTaskSourceId,
    CreatorReplyDraft,
    CreatorSceneReplyScope,
    FormalNoActionDraft,
    FormalNoActionKind,
    FormalNoActionReason,
    SleepDecisionKind,
    SubjectChangeSet,
    SubjectCommitViolation,
    WebResearchRequestDraft,
)
from armi_kernel.contracts import ContractViolation, Digest

_TOP_KEYS_V1 = {
    "schema_version",
    "subject_id",
    "generation_id",
    "episode_id",
    "model_attempt_id",
    "base",
    "candidate_digest",
    "disposition",
    "experiences",
    "components",
    "rejections",
}
_TOP_KEYS_V2 = {*_TOP_KEYS_V1, "capability_requests"}
_TOP_KEYS_V3 = {*_TOP_KEYS_V2, "action_choices"}
_TOP_KEYS_V4 = {*_TOP_KEYS_V3, "web_research_requests"}
_TOP_KEYS_V5 = {*_TOP_KEYS_V3, "codex_delegations"}
_TOP_KEYS_V6 = _TOP_KEYS_V5
_TOP_KEYS_V7 = {*_TOP_KEYS_V6, "activities"}
_TOP_KEYS_V8 = {*_TOP_KEYS_V7, "activity_decisions"}
_TOP_KEYS_V9 = {*_TOP_KEYS_V8, "sleep_decisions"}


def parse_subject_change_set(value: bytes) -> SubjectChangeSet:
    try:
        raw = json.loads(value)
        if type(raw) is not dict:
            raise ValueError
        document = cast(dict[str, Any], raw)
        if document.get("schema_version") not in {
            "armi.subject-change-set.v1",
            "armi.subject-change-set.v2",
            "armi.subject-change-set.v3",
            "armi.subject-change-set.v4",
            "armi.subject-change-set.v5",
            "armi.subject-change-set.v6",
            "armi.subject-change-set.v7",
            "armi.subject-change-set.v8",
            "armi.subject-change-set.v9",
        }:
            raise ValueError
        version = document["schema_version"]
        expected_keys = (
            _TOP_KEYS_V1
            if version.endswith(".v1")
            else _TOP_KEYS_V2
            if version.endswith(".v2")
            else _TOP_KEYS_V3
            if version.endswith(".v3")
            else _TOP_KEYS_V4
            if version.endswith(".v4")
            else _TOP_KEYS_V5
            if version.endswith(".v5")
            else _TOP_KEYS_V6
            if version.endswith(".v6")
            else _TOP_KEYS_V7
            if version.endswith(".v7")
            else _TOP_KEYS_V8
            if version.endswith(".v8")
            else _TOP_KEYS_V9
        )
        if set(document) != expected_keys:
            raise ValueError
        canonical = rfc8785.dumps(cast(Any, document))
        if canonical != value:
            raise ValueError
        base = _object(
            document["base"],
            {
                "subject_version",
                "state_epoch",
                "bundle_activation_id",
                "context_digest",
            },
        )
        experiences = tuple(
            _experience(item) for item in _array(document["experiences"], 16)
        )
        components = tuple(
            _component(item) for item in _array(document["components"], 12)
        )
        capability_requests = tuple(
            _capability(item)
            for item in _array(document.get("capability_requests", []), 4)
        )
        action_choices = tuple(
            _action(item) for item in _array(document.get("action_choices", []), 1)
        )
        web_research_requests = tuple(
            _web_research(item)
            for item in _array(document.get("web_research_requests", []), 1)
        )
        codex_delegations = tuple(
            _codex_delegation(item)
            for item in _array(document.get("codex_delegations", []), 1)
        )
        activities = tuple(
            _activity(item) for item in _array(document.get("activities", []), 4)
        )
        activity_decisions = tuple(
            _activity_decision(item)
            for item in _array(document.get("activity_decisions", []), 1)
        )
        sleep_decisions = tuple(
            _sleep_decision(item)
            for item in _array(document.get("sleep_decisions", []), 1)
        )
        rejections = tuple(
            _rejection(item) for item in _array(document["rejections"], 16)
        )
        result = SubjectChangeSet(
            canonical,
            Digest.from_bytes(canonical),
            _uuid7(document["subject_id"]),
            _uuid7(document["generation_id"]),
            _uuid7(document["episode_id"]),
            _uuid7(document["model_attempt_id"]),
            _nonnegative(base["subject_version"]),
            _nonnegative(base["state_epoch"]),
            _uuid7(base["bundle_activation_id"]),
            Digest(_text(base["context_digest"])),
            Digest(_text(document["candidate_digest"])),
            CandidateDisposition(_text(document["disposition"])),
            experiences,
            components,
            capability_requests,
            action_choices,
            web_research_requests,
            rejections,
            codex_delegations,
            activities,
            activity_decisions,
            sleep_decisions,
        )
        proposal_refs = [
            item.proposal_ref
            for item in (
                *experiences,
                *components,
                *capability_requests,
                *action_choices,
                *web_research_requests,
                *codex_delegations,
                *activities,
                *activity_decisions,
                *sleep_decisions,
                *rejections,
            )
        ]
        if len(proposal_refs) != len(set(proposal_refs)):
            raise ValueError
        change_material = (
            result.experiences
            or result.components
            or result.capability_requests
            or result.web_research_requests
            or result.codex_delegations
            or result.activities
            or result.activity_decisions
            or result.sleep_decisions
        )
        reply = any(isinstance(item, CreatorReplyDraft) for item in action_choices)
        no_action = tuple(
            item for item in action_choices if isinstance(item, FormalNoActionDraft)
        )
        if version.endswith(".v9"):
            if len(sleep_decisions) != 1 or any(
                (
                    experiences,
                    components,
                    capability_requests,
                    action_choices,
                    web_research_requests,
                    codex_delegations,
                    activities,
                    activity_decisions,
                    rejections,
                )
            ):
                raise ValueError
            expected_disposition = {
                "sleep": CandidateDisposition.CHANGE,
                "stay_awake": CandidateDisposition.NO_CHANGE,
                "defer": CandidateDisposition.DEFER,
                "need_information": CandidateDisposition.NEED_INFORMATION,
            }[sleep_decisions[0].decision_kind.value]
            if result.disposition is not expected_disposition:
                raise ValueError
        elif version.endswith(".v8"):
            if len(activity_decisions) != 1 or any(
                (
                    experiences,
                    components,
                    capability_requests,
                    action_choices,
                    web_research_requests,
                    codex_delegations,
                    activities,
                    rejections,
                )
            ):
                raise ValueError
            expected_disposition = {
                "no_action": CandidateDisposition.NO_ACTION,
                "defer": CandidateDisposition.DEFER,
                "need_information": CandidateDisposition.NEED_INFORMATION,
            }.get(
                activity_decisions[0].decision_kind.value,
                CandidateDisposition.CHANGE,
            )
            if result.disposition is not expected_disposition:
                raise ValueError
        else:
            if result.disposition is CandidateDisposition.CHANGE:
                if no_action:
                    raise ValueError
            elif change_material or reply:
                raise ValueError
            if result.disposition in {
                CandidateDisposition.DECLINE,
                CandidateDisposition.NO_ACTION,
            }:
                if (
                    len(no_action) != 1
                    or no_action[0].kind.value != result.disposition.value
                ):
                    raise ValueError
            elif no_action:
                raise ValueError
        return result
    except (
        CandidateViolation,
        ContractViolation,
        KeyError,
        TypeError,
        ValueError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ):
        raise SubjectCommitViolation("SUBJECT-CHANGE-SET-INVALID") from None


def _experience(value: object) -> CandidateExperienceDraft:
    item = _object(
        value,
        {
            "proposal_ref",
            "atomic_group_ref",
            "basis_ordinals",
            "fact_class",
            "first_person_gist",
            "uncertainty",
            "privacy_scope",
        },
    )
    uncertainty = item["uncertainty"]
    return CandidateExperienceDraft(
        _text(item["proposal_ref"]),
        _text(item["atomic_group_ref"]),
        _ordinals(item["basis_ordinals"]),
        CandidateFactClass(_text(item["fact_class"])),
        _text(item["first_person_gist"]),
        None if uncertainty is None else _text(uncertainty),
        _text(item["privacy_scope"]),
    )


def _activity(value: object) -> CandidateActivityDraft:
    item = _object(
        value,
        {
            "proposal_ref",
            "atomic_group_ref",
            "basis_ordinals",
            "fact_class",
            "activity_id",
            "activity_kind",
            "goal",
            "next_safe_step",
            "status",
            "privacy_scope",
        },
    )
    return CandidateActivityDraft(
        _text(item["proposal_ref"]),
        _text(item["atomic_group_ref"]),
        _ordinals(item["basis_ordinals"]),
        CandidateFactClass(_text(item["fact_class"])),
        _uuid7(item["activity_id"]),
        _text(item["goal"]),
        _text(item["next_safe_step"]),
        ActivityStatus(_text(item["status"])),
        _text(item["activity_kind"]),
        _text(item["privacy_scope"]),
    )


def _activity_decision(value: object) -> CandidateActivityDecisionDraft:
    item = _object(
        value,
        {
            "proposal_ref",
            "atomic_group_ref",
            "basis_ordinals",
            "activity_id",
            "current_revision_id",
            "expected_head_version",
            "resource_snapshot_digest",
            "decision_kind",
            "progress_summary",
            "next_safe_step",
            "waiting_summary",
            "resumption_cue",
            "waiting_kind",
            "delay_seconds",
            "terminal_reason",
        },
    )
    return CandidateActivityDecisionDraft(
        _text(item["proposal_ref"]),
        _text(item["atomic_group_ref"]),
        _ordinals(item["basis_ordinals"]),
        _uuid7(item["activity_id"]),
        _uuid7(item["current_revision_id"]),
        _positive(item["expected_head_version"]),
        Digest(_text(item["resource_snapshot_digest"])),
        ActivityAttentionDecisionKind(_text(item["decision_kind"])),
        _optional_text_value(item["progress_summary"]),
        _optional_text_value(item["next_safe_step"]),
        _optional_text_value(item["waiting_summary"]),
        _optional_text_value(item["resumption_cue"]),
        None
        if item["waiting_kind"] is None
        else ActivityWaitingKind(_text(item["waiting_kind"])),
        None if item["delay_seconds"] is None else _positive(item["delay_seconds"]),
        _optional_text_value(item["terminal_reason"]),
    )


def _sleep_decision(value: object) -> CandidateSleepDecisionDraft:
    item = _object(
        value,
        {
            "proposal_ref",
            "atomic_group_ref",
            "basis_ordinals",
            "decision_kind",
            "cycle_anchor_ref",
            "source_digest",
        },
    )
    return CandidateSleepDecisionDraft(
        _text(item["proposal_ref"]),
        _text(item["atomic_group_ref"]),
        _ordinals(item["basis_ordinals"]),
        SleepDecisionKind(_text(item["decision_kind"])),
        _uuid7(item["cycle_anchor_ref"]),
        Digest(_text(item["source_digest"])),
    )


def _component(value: object) -> CandidateComponentDraft:
    item = _object(
        value,
        {
            "proposal_ref",
            "atomic_group_ref",
            "basis_ordinals",
            "fact_class",
            "owner",
            "expected_version",
            "next_state",
            "next_state_digest",
        },
    )
    next_state = rfc8785.dumps(item["next_state"])
    return CandidateComponentDraft(
        _text(item["proposal_ref"]),
        _text(item["atomic_group_ref"]),
        _ordinals(item["basis_ordinals"]),
        CandidateFactClass(_text(item["fact_class"])),
        CandidateOwner(_text(item["owner"])),
        _positive(item["expected_version"]),
        next_state,
        Digest(_text(item["next_state_digest"])),
    )


def _web_research(value: object) -> WebResearchRequestDraft:
    item = _object(
        value,
        {
            "proposal_ref",
            "atomic_group_ref",
            "basis_ordinals",
            "purpose",
            "operation_class",
            "query",
            "query_digest",
        },
    )
    query = _text(item["query"]).encode("utf-8", errors="strict")
    return WebResearchRequestDraft(
        _text(item["proposal_ref"]),
        _text(item["atomic_group_ref"]),
        _ordinals(item["basis_ordinals"]),
        query,
        Digest(_text(item["query_digest"])),
        _text(item["purpose"]),
        _text(item["operation_class"]),
    )


def _codex_delegation(value: object) -> CodexDelegationDraft:
    item = _object(
        value,
        {
            "proposal_ref",
            "atomic_group_ref",
            "basis_ordinals",
            "task_source_id",
            "task_manifest_digest",
            "validator_id",
            "capability_kind",
            "operation",
            "purpose",
        },
    )
    if (
        item["capability_kind"] != "codex.delegated-work"
        or item["operation"] != "execute"
        or item["purpose"] != "delegate_codex_work"
    ):
        raise ValueError
    return CodexDelegationDraft(
        _text(item["proposal_ref"]),
        _text(item["atomic_group_ref"]),
        _ordinals(item["basis_ordinals"]),
        CodexTaskSourceId(_uuid7(item["task_source_id"])),
        Digest(_text(item["task_manifest_digest"])),
        _text(item["validator_id"]),
    )


def _capability(value: object) -> CapabilityRequestDraft:
    item = _object(
        value,
        {
            "proposal_ref",
            "atomic_group_ref",
            "basis_ordinals",
            "capability_kind",
            "operation",
            "scope",
        },
    )
    capability = CapabilityKind(_text(item["capability_kind"]))
    operation = CapabilityOperation(_text(item["operation"]))
    if capability is CapabilityKind.CREATOR_SCENE_REPLY:
        scope = _object(
            item["scope"],
            {
                "subject_id",
                "scene_id",
                "creator_party_id",
                "audience_scope",
                "data_scope",
                "purpose",
                "valid_for_seconds",
                "max_uses",
                "max_payload_bytes",
            },
        )
        parsed_scope = CreatorSceneReplyScope(
            _uuid7(scope["subject_id"]),
            _uuid7(scope["scene_id"]),
            _uuid7(scope["creator_party_id"]),
            _positive(scope["valid_for_seconds"]),
            _positive(scope["max_uses"]),
            _positive(scope["max_payload_bytes"]),
            _text(scope["audience_scope"]),
            _text(scope["data_scope"]),
            _text(scope["purpose"]),
        )
    else:
        scope = _object(
            item["scope"],
            {
                "workspace_scope",
                "artifact_scope",
                "network_access",
                "max_uses",
                "valid_for_seconds",
            },
        )
        if type(scope["network_access"]) is not bool:
            raise ValueError
        parsed_scope = CodexDelegatedWorkScope(
            _positive(scope["valid_for_seconds"]),
            _text(scope["workspace_scope"]),
            _text(scope["artifact_scope"]),
            scope["network_access"],
            _positive(scope["max_uses"]),
        )
    return CapabilityRequestDraft(
        _text(item["proposal_ref"]),
        _text(item["atomic_group_ref"]),
        _ordinals(item["basis_ordinals"]),
        capability,
        operation,
        parsed_scope,
    )


def _rejection(value: object) -> CandidateRejection:
    item = _object(
        value,
        {
            "proposal_ref",
            "atomic_group_ref",
            "basis_ordinals",
            "fact_class",
            "owner",
            "code",
        },
    )
    return CandidateRejection(
        _text(item["proposal_ref"]),
        _text(item["atomic_group_ref"]),
        _ordinals(item["basis_ordinals"]),
        CandidateFactClass(_text(item["fact_class"])),
        CandidateOwner(_text(item["owner"])),
        _text(item["code"]),
    )


def _action(value: object) -> CreatorReplyDraft | FormalNoActionDraft:
    if type(value) is not dict:
        raise ValueError
    action_object = cast(dict[str, Any], value)
    action_kind = action_object.get("action_kind")
    common = {"proposal_ref", "atomic_group_ref", "basis_ordinals", "action_kind"}
    if action_kind == "creator_reply":
        item = _object(
            action_object,
            common
            | {
                "subject_id",
                "scene_id",
                "creator_party_id",
                "capability_kind",
                "operation",
                "audience_scope",
                "data_scope",
                "purpose",
                "media_type",
                "content",
                "content_digest",
            },
        )
        content = _text(item["content"]).encode("utf-8", errors="strict")
        draft = CreatorReplyDraft(
            _text(item["proposal_ref"]),
            _text(item["atomic_group_ref"]),
            _ordinals(item["basis_ordinals"]),
            _uuid7(item["subject_id"]),
            _uuid7(item["scene_id"]),
            _uuid7(item["creator_party_id"]),
            content,
            Digest(_text(item["content_digest"])),
            _text(item["capability_kind"]),
            _text(item["operation"]),
            _text(item["audience_scope"]),
            _text(item["data_scope"]),
            _text(item["purpose"]),
            _text(item["media_type"]),
        )
        return draft
    item = _object(action_object, common | {"decision", "reason_class"})
    return FormalNoActionDraft(
        _text(item["proposal_ref"]),
        _text(item["atomic_group_ref"]),
        _ordinals(item["basis_ordinals"]),
        FormalNoActionKind(_text(item["decision"])),
        FormalNoActionReason(_text(item["reason_class"])),
    )


def _object(value: object, keys: set[str]) -> dict[str, Any]:
    if type(value) is not dict:
        raise ValueError
    result = cast(dict[str, Any], value)
    if set(result) != keys:
        raise ValueError
    return result


def _array(value: object, maximum: int) -> list[object]:
    if type(value) is not list:
        raise ValueError
    result = cast(list[object], value)
    if len(result) > maximum:
        raise ValueError
    return result


def _ordinals(value: object) -> tuple[int, ...]:
    values = _array(value, 8)
    if not values:
        raise ValueError
    return tuple(_positive(item) for item in values)


def _text(value: object) -> str:
    if type(value) is not str:
        raise ValueError
    return value


def _optional_text_value(value: object) -> str | None:
    return None if value is None else _text(value)


def _uuid7(value: object) -> UUID:
    parsed = UUID(_text(value))
    if parsed.version != 7 or str(parsed) != value:
        raise ValueError
    return parsed


def _nonnegative(value: object) -> int:
    if type(value) is not int or value < 0:
        raise ValueError
    return value


def _positive(value: object) -> int:
    parsed = _nonnegative(value)
    if parsed == 0:
        raise ValueError
    return parsed


__all__ = ("parse_subject_change_set",)
