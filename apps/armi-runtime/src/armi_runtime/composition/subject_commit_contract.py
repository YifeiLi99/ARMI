"""Strict parser for the persisted T-03 input artifact."""

from __future__ import annotations

import json
from hashlib import sha256
from typing import Any, cast
from uuid import UUID

import rfc8785
from armi_activity.api import (
    ActivityAttentionDecisionKind,
    ActivityCognitionPort,
    ActivityStatus,
    ActivityViolation,
    ActivityWaitingKind,
    CandidateActivityDecisionDraft,
    CandidateActivityDraft,
    default_activity_cognition,
)
from armi_kernel.application import (
    CandidateComponentDraft,
    CandidateDisposition,
    CandidateExactLifeQueryDraft,
    CandidateExperienceDraft,
    CandidateFactClass,
    CandidateLifeMaterialDraft,
    CandidateOwner,
    CandidateOwnerDraft,
    CandidateRejection,
    CandidateSubjectPromptDraft,
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
    LifeMaterialKind,
    LifeMaterialRevisionKind,
    LifeMaterialStatus,
    LifeRecordKind,
    OtherHumanEndConversationDraft,
    OtherHumanReplyDraft,
    SubjectChangeSet,
    SubjectCommitViolation,
    WebResearchRequestDraft,
)
from armi_kernel.contracts import ContractViolation, Digest
from armi_memory.api import (
    CandidateMemoryDraft,
    CandidateMemoryRevisionDraft,
    MemoryAccessibility,
    MemoryCognitionPort,
    MemoryRelationKind,
    MemoryRevisionKind,
    MemorySourceKind,
    MemoryViolation,
    default_memory_cognition,
)
from armi_relationship.api import (
    RELATIONSHIP_MECHANISM_IDENTITY,
    CandidateRelationshipDraft,
    RelationshipBoundary,
    RelationshipBoundaryAction,
    RelationshipBoundaryKind,
    RelationshipCognitionPort,
    RelationshipCommitment,
    RelationshipCommitmentEvent,
    RelationshipCommitmentEventKind,
    RelationshipCommitmentStatus,
    RelationshipFact,
    RelationshipFactKind,
    RelationshipIssue,
    RelationshipIssueKind,
    RelationshipIssueStatus,
    RelationshipPartyRole,
    RelationshipStatus,
    RelationshipViolation,
)
from armi_sleep.api import (
    CandidateMaintenanceDecisionDraft,
    CandidateSleepDecisionDraft,
    MaintenancePhase,
    MaintenanceWorkOutcome,
    SleepCognitionPort,
    SleepDecisionKind,
    SleepViolation,
    default_sleep_cognition,
)

_TOP_KEYS_V1 = {
    "schema_version",
    "subject_id",
    "generation_id",
    "episode_id",
    "model_attempt_id",
    "base",
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
_TOP_KEYS_V10 = {*_TOP_KEYS_V6, "web_research_requests", "memories"}
_TOP_KEYS_V11 = {*_TOP_KEYS_V10, "memory_revisions"}
_TOP_KEYS_V12 = {*_TOP_KEYS_V11, "relationships"}
_TOP_KEYS_V13 = _TOP_KEYS_V12
_TOP_KEYS_V14 = {*_TOP_KEYS_V13, "materials"}
_TOP_KEYS_V15 = _TOP_KEYS_V14
_TOP_KEYS_V16 = {*_TOP_KEYS_V15, "prompts"}
_TOP_KEYS_V17 = {*_TOP_KEYS_V16, "exact_life_queries"}
_TOP_KEYS_V18 = {*_TOP_KEYS_V17, "activities", "activity_decisions"}
_TOP_KEYS_V19 = {*_TOP_KEYS_V18, "maintenance_decisions"}
_TOP_KEYS_V22 = (_TOP_KEYS_V18 - {"relationships"}) | {"owner_drafts"}
_TOP_KEYS_V23 = (_TOP_KEYS_V22 - {"memories", "memory_revisions"}) | {
    "sleep_decisions",
    "maintenance_decisions",
}
_TOP_KEYS_V24 = _TOP_KEYS_V23 - {"sleep_decisions", "maintenance_decisions"}
_TOP_KEYS_V25 = _TOP_KEYS_V24 - {"activities", "activity_decisions"}


def parse_subject_change_set(
    value: bytes,
    relationship_cognition: RelationshipCognitionPort | None = None,
    memory_cognition: MemoryCognitionPort | None = None,
    sleep_cognition: SleepCognitionPort | None = None,
    activity_cognition: ActivityCognitionPort | None = None,
) -> SubjectChangeSet:
    memory_cognition = memory_cognition or default_memory_cognition()
    sleep_cognition = sleep_cognition or default_sleep_cognition()
    activity_cognition = activity_cognition or default_activity_cognition()
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
            "armi.subject-change-set.v10",
            "armi.subject-change-set.v11",
            "armi.subject-change-set.v12",
            "armi.subject-change-set.v13",
            "armi.subject-change-set.v14",
            "armi.subject-change-set.v15",
            "armi.subject-change-set.v16",
            "armi.subject-change-set.v17",
            "armi.subject-change-set.v18",
            "armi.subject-change-set.v19",
            "armi.subject-change-set.v20",
            "armi.subject-change-set.v21",
            "armi.subject-change-set.v22",
            "armi.subject-change-set.v23",
            "armi.subject-change-set.v24",
            "armi.subject-change-set.v25",
        }:
            raise ValueError
        version = document["schema_version"]
        expected_keys = (
            _TOP_KEYS_V25
            if version.endswith(".v25")
            else _TOP_KEYS_V24
            if version.endswith(".v24")
            else _TOP_KEYS_V23
            if version.endswith(".v23")
            else _TOP_KEYS_V22
            if version.endswith(".v22")
            else _TOP_KEYS_V1
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
            if version.endswith(".v9")
            else _TOP_KEYS_V10
            if version.endswith(".v10")
            else _TOP_KEYS_V11
            if version.endswith(".v11")
            else _TOP_KEYS_V12
            if version.endswith(".v12")
            else _TOP_KEYS_V13
            if version.endswith(".v13")
            else _TOP_KEYS_V14
            if version.endswith(".v14")
            else _TOP_KEYS_V15
            if version.endswith(".v15")
            else _TOP_KEYS_V16
            if version.endswith(".v16")
            else _TOP_KEYS_V17
            if version.endswith(".v17")
            else _TOP_KEYS_V18
            if version.endswith(".v18")
            else _TOP_KEYS_V19
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
            _action(item, version=version)
            for item in _array(document.get("action_choices", []), 1)
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
        maintenance_decisions = tuple(
            _maintenance_decision(item)
            for item in _array(document.get("maintenance_decisions", []), 1)
        )
        memories = tuple(
            _memory(item) for item in _array(document.get("memories", []), 4)
        )
        memory_revisions = tuple(
            _memory_revision(item)
            for item in _array(document.get("memory_revisions", []), 1)
        )
        relationships = tuple(
            _relationship(
                item,
                include_commitments=version.endswith(
                    (
                        ".v13",
                        ".v14",
                        ".v15",
                        ".v16",
                        ".v17",
                        ".v18",
                        ".v19",
                        ".v20",
                        ".v21",
                    )
                ),
            )
            for item in _array(document.get("relationships", []), 1)
        )
        parsed_owner_drafts = (
            tuple(
                _owner_draft(item)
                for item in _array(
                    document.get("owner_drafts", []),
                    8 if version.endswith((".v23", ".v24", ".v25")) else 1,
                )
            )
            if version.endswith((".v22", ".v23", ".v24", ".v25"))
            else tuple(
                _bind_legacy_relationship(item, relationship_cognition)
                for item in relationships
            )
        )
        if version.endswith((".v22", ".v23", ".v24", ".v25")):
            for draft in parsed_owner_drafts:
                if draft.owner == CandidateOwner.MEMORY.value:
                    decoded_memory = memory_cognition.decode(draft.canonical_payload)
                    if (
                        memory_cognition.bind_legacy(
                            decoded_memory,
                            revision=isinstance(
                                decoded_memory, CandidateMemoryRevisionDraft
                            ),
                        )
                        != draft
                    ):
                        raise ValueError
                elif draft.owner == CandidateOwner.RELATIONSHIP.value:
                    if (
                        relationship_cognition is None
                        or relationship_cognition.bind(
                            relationship_cognition.decode_change_set(
                                draft.canonical_payload
                            )
                        )
                        != draft
                    ):
                        raise ValueError
                elif draft.owner == CandidateOwner.SLEEP.value:
                    decoded_sleep = sleep_cognition.decode(draft.canonical_payload)
                    if (
                        sleep_cognition.bind_legacy(
                            decoded_sleep,
                            maintenance=isinstance(
                                decoded_sleep, CandidateMaintenanceDecisionDraft
                            ),
                        )
                        != draft
                    ):
                        raise ValueError
                elif draft.owner == CandidateOwner.ACTIVITY.value and version.endswith(
                    ".v25"
                ):
                    decoded_activity = activity_cognition.decode(
                        draft.canonical_payload
                    )
                    if (
                        activity_cognition.bind_legacy(
                            decoded_activity,
                            decision=isinstance(
                                decoded_activity, CandidateActivityDecisionDraft
                            ),
                        )
                        != draft
                    ):
                        raise ValueError
                else:
                    raise ValueError
        memory_owner_drafts = (
            *(memory_cognition.bind_legacy(item, revision=False) for item in memories),
            *(
                memory_cognition.bind_legacy(item, revision=True)
                for item in memory_revisions
            ),
        )
        sleep_owner_drafts = (
            *(
                sleep_cognition.bind_legacy(item, maintenance=False)
                for item in sleep_decisions
            ),
            *(
                sleep_cognition.bind_legacy(item, maintenance=True)
                for item in maintenance_decisions
            ),
        )
        activity_owner_drafts = (
            *(
                activity_cognition.bind_legacy(item, decision=False)
                for item in activities
            ),
            *(
                activity_cognition.bind_legacy(item, decision=True)
                for item in activity_decisions
            ),
        )
        owner_drafts = (
            *memory_owner_drafts,
            *sleep_owner_drafts,
            *activity_owner_drafts,
            *parsed_owner_drafts,
        )
        materials = tuple(
            _material(
                item,
                include_mutation=version.endswith(
                    (
                        ".v15",
                        ".v16",
                        ".v17",
                        ".v18",
                        ".v19",
                        ".v22",
                        ".v23",
                        ".v24",
                        ".v25",
                    )
                ),
            )
            for item in _array(document.get("materials", []), 1)
        )
        prompts = tuple(
            _prompt(item) for item in _array(document.get("prompts", []), 1)
        )
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
            components,
            capability_requests,
            action_choices,
            web_research_requests,
            rejections,
            codex_delegations,
            owner_drafts,
            materials,
            prompts,
            exact_life_queries,
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
                *owner_drafts,
                *materials,
                *prompts,
                *exact_life_queries,
                *rejections,
            )
        ]
        if len(proposal_refs) != len(set(proposal_refs)):
            raise ValueError
        experience_by_ref = {item.proposal_ref: item for item in experiences}
        if any(
            memory.source_experience_ref not in experience_by_ref
            or experience_by_ref[memory.source_experience_ref].atomic_group_ref
            != memory.atomic_group_ref
            or experience_by_ref[memory.source_experience_ref].fact_class
            is not memory.fact_class
            for memory in memories
        ):
            raise ValueError
        if any(
            relationship.source_experience_ref not in experience_by_ref
            or experience_by_ref[relationship.source_experience_ref].atomic_group_ref
            != relationship.atomic_group_ref
            for relationship in relationships
        ):
            raise ValueError
        if any(
            not any(
                experience.atomic_group_ref == prompt.atomic_group_ref
                for experience in experiences
            )
            for prompt in prompts
        ):
            raise ValueError
        change_material = (
            result.experiences
            or result.components
            or result.capability_requests
            or result.web_research_requests
            or result.codex_delegations
            or result.owner_drafts
            or result.materials
            or result.prompts
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
        if decoded_sleep_owners and isinstance(
            decoded_sleep_owners[0], CandidateSleepDecisionDraft
        ):
            pass
        elif version.endswith((".v20", ".v21")):
            other_actions = tuple(
                item
                for item in action_choices
                if isinstance(
                    item,
                    (OtherHumanReplyDraft, OtherHumanEndConversationDraft),
                )
            )
            if any(
                (
                    components,
                    capability_requests,
                    web_research_requests,
                    codex_delegations,
                    activities,
                    activity_decisions,
                    sleep_decisions,
                    memories,
                    memory_revisions,
                    materials,
                    prompts,
                    exact_life_queries,
                    maintenance_decisions,
                    rejections,
                )
            ):
                raise ValueError
            if owner_drafts and (
                len(owner_drafts) != 1
                or len(experiences) != 1
                or owner_drafts[0].atomic_group_ref != experiences[0].atomic_group_ref
            ):
                raise ValueError
            if result.disposition is CandidateDisposition.CHANGE:
                valid_action_shape = (
                    (len(other_actions) == 1 and len(action_choices) == 1)
                    or (len(no_action) == 1 and len(action_choices) == 1)
                    or not action_choices
                )
                if not valid_action_shape or not (change_material or other_actions):
                    raise ValueError
            elif result.disposition is CandidateDisposition.NO_ACTION:
                if len(no_action) != 1 or len(action_choices) != 1:
                    raise ValueError
            elif result.disposition is CandidateDisposition.DEFER:
                if action_choices:
                    raise ValueError
            else:
                raise ValueError
        elif version.endswith(".v19"):
            if (
                len(maintenance_decisions) != 1
                or len(memory_revisions) > 1
                or any(
                    (
                        experiences,
                        components,
                        capability_requests,
                        action_choices,
                        web_research_requests,
                        codex_delegations,
                        activities,
                        activity_decisions,
                        sleep_decisions,
                        memories,
                        relationships,
                        materials,
                        prompts,
                        exact_life_queries,
                        rejections,
                    )
                )
                or result.disposition is not CandidateDisposition.CHANGE
            ):
                raise ValueError
            decision = maintenance_decisions[0]
            if decision.memory_proposal_ref is None:
                if memory_revisions:
                    raise ValueError
            elif (
                len(memory_revisions) != 1
                or memory_revisions[0].proposal_ref != decision.memory_proposal_ref
                or memory_revisions[0].atomic_group_ref != decision.atomic_group_ref
            ):
                raise ValueError
        elif version.endswith(".v9"):
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


def _memory(value: object) -> CandidateMemoryDraft:
    item = _object(
        value,
        {
            "proposal_ref",
            "atomic_group_ref",
            "basis_ordinals",
            "fact_class",
            "source_experience_ref",
            "source_kind",
            "summary",
            "mechanism_identity",
            "privacy_scope",
        },
    )
    return CandidateMemoryDraft(
        _text(item["proposal_ref"]),
        _text(item["atomic_group_ref"]),
        _ordinals(item["basis_ordinals"]),
        CandidateFactClass(_text(item["fact_class"])),
        _text(item["source_experience_ref"]),
        MemorySourceKind(_text(item["source_kind"])),
        _text(item["summary"]),
        _text(item["mechanism_identity"]),
        _text(item["privacy_scope"]),
    )


def _material(
    value: object,
    *,
    include_mutation: bool,
) -> CandidateLifeMaterialDraft:
    keys = {
        "proposal_ref",
        "atomic_group_ref",
        "basis_ordinals",
        "material_id",
        "owner_party_id",
        "material_kind",
        "current_revision_id",
        "expected_head_version",
        "title",
        "body",
        "metadata",
        "material_status",
        "privacy_status",
        "source_kind",
    }
    if include_mutation:
        keys.add("revision_kind")
    item = _object(
        value,
        keys,
    )
    current_revision_id = item["current_revision_id"]
    body_value = item["body"]
    body = (
        None
        if body_value is None and include_mutation
        else _text(body_value).encode("utf-8", errors="strict")
    )
    metadata_value = item["metadata"]
    if type(metadata_value) is not dict or any(
        type(key) is not str or type(metadata_item) is not str
        for key, metadata_item in cast(dict[object, object], metadata_value).items()
    ):
        raise ValueError
    metadata = cast(dict[str, str], metadata_value)
    revision_kind = (
        None
        if not include_mutation
        else LifeMaterialRevisionKind(_text(item["revision_kind"]))
    )
    return CandidateLifeMaterialDraft(
        _text(item["proposal_ref"]),
        _text(item["atomic_group_ref"]),
        _ordinals(item["basis_ordinals"]),
        _uuid7(item["material_id"]),
        _uuid7(item["owner_party_id"]),
        LifeMaterialKind(_text(item["material_kind"])),
        None if current_revision_id is None else _uuid7(current_revision_id),
        _nonnegative(item["expected_head_version"]),
        _text(item["title"]),
        body,
        tuple(sorted(metadata.items())),
        LifeMaterialStatus(_text(item["material_status"])),
        _text(item["privacy_status"]),
        _text(item["source_kind"]),
        (
            None
            if revision_kind
            in {LifeMaterialRevisionKind.CREATED, LifeMaterialRevisionKind.UPDATED}
            else revision_kind
        ),
    )


def _memory_revision(value: object) -> CandidateMemoryRevisionDraft:
    item = _object(
        value,
        {
            "proposal_ref",
            "atomic_group_ref",
            "basis_ordinals",
            "fact_class",
            "memory_id",
            "current_revision_id",
            "expected_head_version",
            "revision_kind",
            "accessibility",
            "source_kind",
            "summary",
            "uncertainty",
            "related_memory_id",
            "relation_kind",
            "mechanism_identity",
            "mechanism_config_identity",
            "privacy_scope",
        },
    )
    related_memory_id = item["related_memory_id"]
    relation_kind = item["relation_kind"]
    return CandidateMemoryRevisionDraft(
        _text(item["proposal_ref"]),
        _text(item["atomic_group_ref"]),
        _ordinals(item["basis_ordinals"]),
        CandidateFactClass(_text(item["fact_class"])),
        _uuid7(item["memory_id"]),
        _uuid7(item["current_revision_id"]),
        _positive(item["expected_head_version"]),
        MemoryRevisionKind(_text(item["revision_kind"])),
        MemoryAccessibility(_text(item["accessibility"])),
        MemorySourceKind(_text(item["source_kind"])),
        _text(item["summary"]),
        _optional_text_value(item["uncertainty"]),
        None if related_memory_id is None else _uuid7(related_memory_id),
        None if relation_kind is None else MemoryRelationKind(_text(relation_kind)),
        _text(item["mechanism_identity"]),
        _text(item["mechanism_config_identity"]),
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
    if owner not in {"activity", "memory", "relationship", "sleep"}:
        raise ValueError
    return CandidateOwnerDraft(
        _text(item["proposal_ref"]),
        _text(item["atomic_group_ref"]),
        _ordinals(item["basis_ordinals"]),
        CandidateFactClass(_text(item["fact_class"])),
        owner,
        rfc8785.dumps(item["payload"]),
    )


def _bind_legacy_relationship(
    value: CandidateRelationshipDraft,
    cognition: RelationshipCognitionPort | None,
) -> CandidateOwnerDraft:
    if cognition is None:
        raise ValueError
    return cognition.bind(value)


def _legacy_fact_id(
    relationship_id: UUID,
    ordinal: int,
    kind: str,
    summary: str,
) -> UUID:
    digest = bytearray(
        sha256(f"{relationship_id}:{ordinal}:{kind}:{summary}".encode()).digest()[:16]
    )
    digest[6] = (digest[6] & 0x0F) | 0x70
    digest[8] = (digest[8] & 0x3F) | 0x80
    return UUID(bytes=bytes(digest))


def _relationship(
    value: object,
    *,
    include_commitments: bool,
) -> CandidateRelationshipDraft:
    keys = {
        "proposal_ref",
        "atomic_group_ref",
        "basis_ordinals",
        "fact_class",
        "relationship_id",
        "subject_party_id",
        "other_party_id",
        "current_revision_id",
        "expected_head_version",
        "source_experience_ref",
        "facts",
        "interpretation",
        "boundaries",
        "status",
        "scope",
        "mechanism_identity",
        "privacy_scope",
    }
    if include_commitments:
        keys.update({"commitments", "open_issues", "commitment_event"})
    item = _object(
        value,
        keys,
    )
    current_revision_id = item["current_revision_id"]
    relationship_id = _uuid7(item["relationship_id"])
    raw_facts = _array(item["facts"], 64)
    return CandidateRelationshipDraft(
        proposal_ref=_text(item["proposal_ref"]),
        atomic_group_ref=_text(item["atomic_group_ref"]),
        basis_ordinals=_ordinals(item["basis_ordinals"]),
        fact_class=CandidateFactClass(_text(item["fact_class"])),
        relationship_id=relationship_id,
        subject_party_id=_uuid7(item["subject_party_id"]),
        other_party_id=_uuid7(item["other_party_id"]),
        current_revision_id=(
            None if current_revision_id is None else _uuid7(current_revision_id)
        ),
        expected_head_version=_nonnegative(item["expected_head_version"]),
        source_experience_ref=_text(item["source_experience_ref"]),
        facts=tuple(
            RelationshipFact(
                _legacy_fact_id(
                    relationship_id,
                    ordinal,
                    _text(fact["kind"]),
                    _text(fact["summary"]),
                ),
                RelationshipFactKind(_text(fact["kind"])),
                _text(fact["summary"]),
            )
            for ordinal, fact in enumerate(
                (_object(raw, {"kind", "summary"}) for raw in raw_facts),
                start=1,
            )
        ),
        interpretation=_text(item["interpretation"]),
        boundaries=tuple(
            RelationshipBoundary(
                RelationshipPartyRole(_text(boundary["party_role"])),
                RelationshipBoundaryKind(_text(boundary["kind"])),
                RelationshipBoundaryAction(_text(boundary["action"])),
                _text(boundary["summary"]),
            )
            for boundary in (
                _object(raw, {"party_role", "kind", "action", "summary"})
                for raw in _array(item["boundaries"], 16)
            )
        ),
        status=RelationshipStatus(_text(item["status"])),
        commitments=()
        if not include_commitments
        else tuple(
            RelationshipCommitment(
                _uuid7(commitment["commitment_id"]),
                RelationshipPartyRole(_text(commitment["party_role"])),
                _text(commitment["scope"]),
                _text(commitment["content"]),
                RelationshipCommitmentStatus(_text(commitment["status"])),
                RelationshipCommitmentEventKind(_text(commitment["last_event_kind"])),
                _text(commitment["last_event_summary"]),
            )
            for commitment in (
                _object(
                    raw,
                    {
                        "commitment_id",
                        "party_role",
                        "scope",
                        "content",
                        "status",
                        "last_event_kind",
                        "last_event_summary",
                    },
                )
                for raw in _array(item["commitments"], 16)
            )
        ),
        open_issues=()
        if not include_commitments
        else tuple(
            RelationshipIssue(
                _uuid7(issue["issue_id"]),
                RelationshipIssueKind(_text(issue["kind"])),
                tuple(_uuid7(value) for value in _array(issue["commitment_ids"], 2)),
                _text(issue["summary"]),
                RelationshipIssueStatus(_text(issue["status"])),
            )
            for issue in (
                _object(
                    raw,
                    {"issue_id", "kind", "commitment_ids", "summary", "status"},
                )
                for raw in _array(item["open_issues"], 32)
            )
        ),
        commitment_event=(
            _relationship_commitment_event(item["commitment_event"])
            if include_commitments
            else None
        ),
        scope=_text(item["scope"]),
        mechanism_identity=RELATIONSHIP_MECHANISM_IDENTITY,
        privacy_scope=_text(item["privacy_scope"]),
    )


def _relationship_commitment_event(
    value: object,
) -> RelationshipCommitmentEvent | None:
    if value is None:
        return None
    item = _object(
        value,
        {"commitment_id", "kind", "summary", "related_commitment_id"},
    )
    related_commitment_id = item["related_commitment_id"]
    return RelationshipCommitmentEvent(
        _uuid7(item["commitment_id"]),
        RelationshipCommitmentEventKind(_text(item["kind"])),
        _text(item["summary"]),
        (None if related_commitment_id is None else _uuid7(related_commitment_id)),
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
        },
    )
    return CandidateSleepDecisionDraft(
        _text(item["proposal_ref"]),
        _text(item["atomic_group_ref"]),
        _ordinals(item["basis_ordinals"]),
        SleepDecisionKind(_text(item["decision_kind"])),
        _uuid7(item["cycle_anchor_ref"]),
    )


def _maintenance_decision(value: object) -> CandidateMaintenanceDecisionDraft:
    item = _object(
        value,
        {
            "proposal_ref",
            "atomic_group_ref",
            "basis_ordinals",
            "maintenance_session_id",
            "current_revision_id",
            "expected_head_version",
            "phase",
            "outcome",
            "result_summary",
            "creator_visible_problem",
            "memory_proposal_ref",
        },
    )
    return CandidateMaintenanceDecisionDraft(
        _text(item["proposal_ref"]),
        _text(item["atomic_group_ref"]),
        _ordinals(item["basis_ordinals"]),
        _uuid7(item["maintenance_session_id"]),
        _uuid7(item["current_revision_id"]),
        _positive(item["expected_head_version"]),
        MaintenancePhase(_text(item["phase"])),
        MaintenanceWorkOutcome(_text(item["outcome"])),
        _text(item["result_summary"]),
        _optional_text_value(item["creator_visible_problem"]),
        _optional_text_value(item["memory_proposal_ref"]),
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
    )


def _prompt(value: object) -> CandidateSubjectPromptDraft:
    item = _object(
        value,
        {
            "proposal_ref",
            "atomic_group_ref",
            "basis_ordinals",
            "fact_class",
            "prompt_document_id",
            "current_revision_id",
            "expected_revision_no",
            "content",
        },
    )
    content = _object(
        item["content"],
        {
            "schema_version",
            "cognition_method",
            "expression_method",
            "reflection_method",
        },
    )
    if content["schema_version"] != "armi.subject-prompt.v1":
        raise ValueError
    for key in ("cognition_method", "expression_method", "reflection_method"):
        text = _text(content[key])
        if not 1 <= len(text) <= 512 or not text.strip() or "\x00" in text:
            raise ValueError
    content_bytes = rfc8785.dumps(cast(Any, content))
    return CandidateSubjectPromptDraft(
        _text(item["proposal_ref"]),
        _text(item["atomic_group_ref"]),
        _ordinals(item["basis_ordinals"]),
        CandidateFactClass(_text(item["fact_class"])),
        _uuid7(item["prompt_document_id"]),
        (
            None
            if item["current_revision_id"] is None
            else _uuid7(item["current_revision_id"])
        ),
        _nonnegative(item["expected_revision_no"]),
        content_bytes,
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
        CandidateOwner(_text(item["owner"])),
        _text(item["code"]),
    )


def _action(
    value: object,
    *,
    version: str,
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
        operation = _text(item["operation"])
        if version.endswith(".v20") and operation == "deliver_local":
            operation = "send"
        return OtherHumanReplyDraft(
            _text(item["proposal_ref"]),
            _text(item["atomic_group_ref"]),
            _ordinals(item["basis_ordinals"]),
            _uuid7(item["subject_id"]),
            _uuid7(item["scene_id"]),
            _uuid7(item["other_party_id"]),
            content,
            _text(item["capability_kind"]),
            operation,
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
