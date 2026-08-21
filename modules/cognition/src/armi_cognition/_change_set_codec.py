"""Strict parser for the persisted T-03 input artifact."""

from __future__ import annotations

import json
from typing import Any, cast
from uuid import UUID

import rfc8785
from armi_activity.api import (
    ActivityCognitionPort,
    ActivityViolation,
)
from armi_capability.api import (
    CapabilityKind,
    CapabilityOperation,
    CapabilityRequestDraft,
    CodexDelegatedWorkScope,
    CreatorSceneReplyScope,
)
from armi_codex.api import CodexDelegationDraft, CodexTaskSourceId
from armi_expression.api import (
    CreatorReplyDraft,
    FormalNoActionDraft,
    FormalNoActionKind,
    FormalNoActionReason,
    OtherHumanEndConversationDraft,
    OtherHumanReplyDraft,
)
from armi_kernel.application import (
    CandidateDisposition,
    CandidateExperienceDraft,
    CandidateFactClass,
    CandidateOwnerDraft,
    CandidateOwnerIdentity,
    CandidateRejection,
    CandidateViolation,
    LifeRecordKind,
    SubjectCommitViolation,
)
from armi_kernel.contracts import ContractViolation, Digest
from armi_material.api import (
    MaterialCognitionPort,
    MaterialViolation,
)
from armi_memory.api import (
    MemoryCognitionPort,
    MemoryViolation,
)
from armi_mood.api import MoodCognitionPort, MoodViolation
from armi_prompt.api import (
    PromptCognitionPort,
    PromptViolation,
)
from armi_relationship.api import (
    RelationshipCognitionPort,
    RelationshipViolation,
)
from armi_sleep.api import (
    CandidateMaintenanceDecisionDraft,
    CandidateSleepDecisionDraft,
    SleepCognitionPort,
    SleepDecisionKind,
    SleepViolation,
)
from armi_subject_state.api import (
    SubjectStateCognitionPort,
    SubjectStateViolation,
)
from armi_web_observation.api import WebResearchRequestDraft

from ._owners import CandidateOwner
from .api import CandidateExactLifeQueryDraft, SubjectChangeSet

_TOP_KEYS = {
    "schema_version",
    "subject_id",
    "generation_id",
    "episode_id",
    "model_attempt_id",
    "base",
    "disposition",
    "experiences",
    "rejections",
    "capability_requests",
    "action_choices",
    "web_research_requests",
    "codex_delegations",
    "owner_drafts",
    "exact_life_queries",
}


def parse_subject_change_set(
    value: bytes,
    relationship_cognition: RelationshipCognitionPort,
    memory_cognition: MemoryCognitionPort,
    sleep_cognition: SleepCognitionPort,
    activity_cognition: ActivityCognitionPort,
    material_cognition: MaterialCognitionPort,
    subject_state_cognition: SubjectStateCognitionPort,
    mood_cognition: MoodCognitionPort,
    prompt_cognition: PromptCognitionPort,
) -> SubjectChangeSet:
    try:
        raw = json.loads(value)
        if type(raw) is not dict:
            raise ValueError
        document = cast(dict[str, Any], raw)
        if document.get("schema_version") != "armi.subject-change-set.v29":
            raise ValueError
        if set(document) != _TOP_KEYS:
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
        owner_drafts = tuple(
            _owner_draft(item) for item in _array(document["owner_drafts"], 13)
        )
        for draft in owner_drafts:
            if draft.owner == CandidateOwner.MEMORY.value:
                decoded_memory = memory_cognition.decode(draft.canonical_payload)
                if memory_cognition.bind(decoded_memory) != draft:
                    raise ValueError
            elif draft.owner == CandidateOwner.RELATIONSHIP.value:
                if (
                    relationship_cognition.bind(
                        relationship_cognition.decode_change_set(
                            draft.canonical_payload
                        )
                    )
                    != draft
                ):
                    raise ValueError
            elif draft.owner == CandidateOwner.SLEEP.value:
                decoded_sleep = sleep_cognition.decode(draft.canonical_payload)
                if sleep_cognition.bind(decoded_sleep) != draft:
                    raise ValueError
            elif draft.owner == CandidateOwner.ACTIVITY.value:
                decoded_activity = activity_cognition.decode(draft.canonical_payload)
                if activity_cognition.bind(decoded_activity) != draft:
                    raise ValueError
            elif draft.owner == CandidateOwner.MATERIAL.value:
                if (
                    material_cognition.bind(
                        material_cognition.decode(draft.canonical_payload)
                    )
                    != draft
                ):
                    raise ValueError
            elif draft.owner in {
                CandidateOwner.SELF.value,
                CandidateOwner.MIND.value,
                CandidateOwner.LIFE_MODE.value,
            }:
                if (
                    subject_state_cognition.bind(
                        subject_state_cognition.decode(draft.canonical_payload)
                    )
                    != draft
                ):
                    raise ValueError
            elif draft.owner == CandidateOwner.MOOD.value:
                if (
                    mood_cognition.bind(mood_cognition.decode(draft.canonical_payload))
                    != draft
                ):
                    raise ValueError
            elif draft.owner == CandidateOwner.PROMPT.value:
                if (
                    prompt_cognition.bind(
                        prompt_cognition.decode(draft.canonical_payload)
                    )
                    != draft
                ):
                    raise ValueError
            else:
                raise ValueError
        exact_life_queries = tuple(
            _exact_life_query(item)
            for item in _array(document.get("exact_life_queries", []), 1)
        )
        rejections = tuple(
            _rejection(item) for item in _array(document["rejections"], 16)
        )
        result = SubjectChangeSet(
            canonical,
            _uuid7(document["subject_id"]),
            _uuid7(document["generation_id"]),
            _uuid7(document["episode_id"]),
            _uuid7(document["model_attempt_id"]),
            _nonnegative(base["subject_version"]),
            _nonnegative(base["state_epoch"]),
            _uuid7(base["bundle_activation_id"]),
            Digest(_text(base["context_digest"])),
            CandidateDisposition(_text(document["disposition"])),
            experiences,
            capability_requests,
            action_choices,
            web_research_requests,
            rejections,
            codex_delegations,
            owner_drafts,
            exact_life_queries,
        )
        proposal_refs = [
            item.proposal_ref
            for item in (
                *experiences,
                *capability_requests,
                *action_choices,
                *web_research_requests,
                *codex_delegations,
                *owner_drafts,
                *exact_life_queries,
                *rejections,
            )
        ]
        if len(proposal_refs) != len(set(proposal_refs)):
            raise ValueError
        change_material = (
            result.experiences
            or result.capability_requests
            or result.web_research_requests
            or result.codex_delegations
            or result.owner_drafts
            or result.exact_life_queries
        )
        reply = any(
            isinstance(item, (CreatorReplyDraft, OtherHumanReplyDraft))
            for item in action_choices
        )
        no_action = tuple(
            item for item in action_choices if isinstance(item, FormalNoActionDraft)
        )
        decoded_sleep_owners = tuple(
            sleep_cognition.decode(item.canonical_payload)
            for item in owner_drafts
            if item.owner == CandidateOwner.SLEEP.value
        )
        if len(decoded_sleep_owners) > 1:
            raise ValueError
        if decoded_sleep_owners and isinstance(
            decoded_sleep_owners[0], CandidateMaintenanceDecisionDraft
        ):
            decision = decoded_sleep_owners[0]
            memory_drafts = tuple(
                item
                for item in owner_drafts
                if item.owner == CandidateOwner.MEMORY.value
            )
            if decision.memory_proposal_ref is None:
                if memory_drafts:
                    raise ValueError
            elif (
                len(memory_drafts) != 1
                or memory_drafts[0].proposal_ref != decision.memory_proposal_ref
                or memory_drafts[0].atomic_group_ref != decision.atomic_group_ref
            ):
                raise ValueError
            if result.disposition is not CandidateDisposition.CHANGE:
                raise ValueError
        elif decoded_sleep_owners:
            decision = cast(CandidateSleepDecisionDraft, decoded_sleep_owners[0])
            expected_disposition = {
                SleepDecisionKind.SLEEP: CandidateDisposition.CHANGE,
                SleepDecisionKind.STAY_AWAKE: CandidateDisposition.NO_CHANGE,
                SleepDecisionKind.DEFER: CandidateDisposition.DEFER,
                SleepDecisionKind.NEED_INFORMATION: CandidateDisposition.NEED_INFORMATION,
            }[decision.decision_kind]
            if result.disposition is not expected_disposition:
                raise ValueError
        if not decoded_sleep_owners:
            if result.disposition is CandidateDisposition.CHANGE:
                if no_action and not owner_drafts:
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
            elif no_action and not owner_drafts:
                raise ValueError
        return result
    except (
        CandidateViolation,
        ContractViolation,
        MemoryViolation,
        RelationshipViolation,
        SleepViolation,
        ActivityViolation,
        MaterialViolation,
        MoodViolation,
        PromptViolation,
        SubjectStateViolation,
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


def _owner_draft(value: object) -> CandidateOwnerDraft:
    item = _object(
        value,
        {
            "proposal_ref",
            "atomic_group_ref",
            "basis_ordinals",
            "fact_class",
            "owner",
            "payload",
        },
    )
    owner = _text(item["owner"])
    if owner not in {
        "activity",
        "life_mode",
        "material",
        "memory",
        "mind",
        "mood",
        "prompt",
        "relationship",
        "self",
        "sleep",
    }:
        raise ValueError
    return CandidateOwnerDraft(
        _text(item["proposal_ref"]),
        _text(item["atomic_group_ref"]),
        _ordinals(item["basis_ordinals"]),
        CandidateFactClass(_text(item["fact_class"])),
        owner,
        rfc8785.dumps(item["payload"]),
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
        },
    )
    query = _text(item["query"]).encode("utf-8", errors="strict")
    return WebResearchRequestDraft(
        _text(item["proposal_ref"]),
        _text(item["atomic_group_ref"]),
        _ordinals(item["basis_ordinals"]),
        query,
        _text(item["purpose"]),
        _text(item["operation_class"]),
    )


def _exact_life_query(value: object) -> CandidateExactLifeQueryDraft:
    item = _object(
        value,
        {
            "proposal_ref",
            "atomic_group_ref",
            "basis_ordinals",
            "fact_class",
            "record_kind",
            "query_text",
            "limit",
        },
    )
    query_text = item["query_text"]
    if query_text is not None:
        query_text = _text(query_text)
    return CandidateExactLifeQueryDraft(
        _text(item["proposal_ref"]),
        _text(item["atomic_group_ref"]),
        _ordinals(item["basis_ordinals"]),
        CandidateFactClass(_text(item["fact_class"])),
        LifeRecordKind(_text(item["record_kind"])),
        query_text,
        _positive(item["limit"]),
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
        CandidateOwnerIdentity(_text(item["owner"])),
        _text(item["code"]),
    )


def _action(
    value: object,
) -> (
    CreatorReplyDraft
    | OtherHumanReplyDraft
    | OtherHumanEndConversationDraft
    | FormalNoActionDraft
):
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
            _text(item["capability_kind"]),
            _text(item["operation"]),
            _text(item["audience_scope"]),
            _text(item["data_scope"]),
            _text(item["purpose"]),
            _text(item["media_type"]),
        )
        return draft
    if action_kind == "other_human_reply":
        item = _object(
            action_object,
            common
            | {
                "subject_id",
                "scene_id",
                "other_party_id",
                "capability_kind",
                "operation",
                "audience_scope",
                "data_scope",
                "purpose",
                "media_type",
                "content",
            },
        )
        content = _text(item["content"]).encode("utf-8", errors="strict")
        return OtherHumanReplyDraft(
            _text(item["proposal_ref"]),
            _text(item["atomic_group_ref"]),
            _ordinals(item["basis_ordinals"]),
            _uuid7(item["subject_id"]),
            _uuid7(item["scene_id"]),
            _uuid7(item["other_party_id"]),
            content,
            _text(item["capability_kind"]),
            _text(item["operation"]),
            _text(item["audience_scope"]),
            _text(item["data_scope"]),
            _text(item["purpose"]),
            _text(item["media_type"]),
        )
    if action_kind == "other_human_end_conversation":
        item = _object(
            action_object,
            common | {"subject_id", "scene_id", "other_party_id"},
        )
        return OtherHumanEndConversationDraft(
            _text(item["proposal_ref"]),
            _text(item["atomic_group_ref"]),
            _ordinals(item["basis_ordinals"]),
            _uuid7(item["subject_id"]),
            _uuid7(item["scene_id"]),
            _uuid7(item["other_party_id"]),
        )
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
