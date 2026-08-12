"""Purpose-specific Context inclusion and placement policy."""

from __future__ import annotations

from dataclasses import dataclass

from .api import (
    ContextItemCandidate,
    ContextLayer,
    ContextRequirement,
    ContextViolation,
)


@dataclass(frozen=True, slots=True)
class ContextItemPolicy:
    requirement: ContextRequirement
    layer: ContextLayer


@dataclass(frozen=True, slots=True)
class ContextAssemblyProfile:
    purpose: str
    required_kinds: frozenset[str]
    forbidden_kinds: frozenset[str]
    retrieval_kinds: frozenset[str]

    def allows(self, item_kind: str) -> bool:
        return item_kind not in self.forbidden_kinds

    def policy_for(
        self,
        item_kind: str,
        *,
        requested_required: bool,
    ) -> ContextItemPolicy:
        if item_kind in self.forbidden_kinds:
            raise ContextViolation("CTX-POLICY-FORBIDDEN")
        requirement = (
            ContextRequirement.REQUIRED
            if requested_required or item_kind in self.required_kinds
            else ContextRequirement.OPTIONAL
        )
        return ContextItemPolicy(requirement, _layer_for(item_kind))

    def candidate_policy(
        self,
        item_kind: str,
        *,
        requested_required: bool,
    ) -> ContextItemPolicy:
        """Place a source candidate before the profile's forbidden-item filter."""
        requirement = (
            ContextRequirement.REQUIRED
            if requested_required or item_kind in self.required_kinds
            else ContextRequirement.OPTIONAL
        )
        return ContextItemPolicy(requirement, _layer_for(item_kind))

    def validate(self, candidates: tuple[ContextItemCandidate, ...]) -> None:
        present = {item.item_kind for item in candidates if item.content is not None}
        if not self.required_kinds.issubset(present):
            raise ContextViolation("CTX-SOURCE-MISSING")


_STABLE_KINDS = frozenset(
    {
        "runtime_identity",
        "current_purpose",
        "fixed_prompt",
        "creator_prompt",
        "subject_prompt",
        "self",
        "mind",
        "mood",
    }
)
_SCOPE_KINDS = frozenset({"current_scene"})
_HISTORY_KINDS = frozenset({"recent_scene_turn"})


def _layer_for(item_kind: str) -> ContextLayer:
    if item_kind in _STABLE_KINDS:
        return ContextLayer.STABLE_PREFIX
    if item_kind in _SCOPE_KINDS:
        return ContextLayer.SCOPE_CONTEXT
    if item_kind in _HISTORY_KINDS:
        return ContextLayer.CONVERSATION_HISTORY
    return ContextLayer.TURN_TAIL


_SUBJECT_SKELETON = frozenset(
    {"runtime_identity", "current_purpose", "fixed_prompt", "self", "mind", "mood"}
)
_PRIVATE_RECALL = frozenset({"current_memory", "current_material", "recall_status"})
_PRIVATE_LIFE = frozenset(
    {
        "current_life_opportunity",
        "current_maintenance_window",
        "current_maintenance_phase",
        "current_activities",
        "current_activity",
        "resource_snapshot",
        "life_mode",
        "activities",
        "activity",
        "maintenance_window",
        "maintenance_phase",
        "web_search_availability",
        "capability_catalog",
    }
)


def _profile(
    purpose: str,
    *,
    required: frozenset[str] = frozenset(),
    forbidden: frozenset[str] = frozenset(),
    retrieval: frozenset[str] = frozenset(),
) -> ContextAssemblyProfile:
    return ContextAssemblyProfile(
        purpose,
        _SUBJECT_SKELETON | required,
        forbidden,
        retrieval,
    )


_PROFILES = {
    "consider_creator_input": _profile(
        "consider_creator_input",
        required=frozenset(
            {"current_scene", "current_relationship", "current_evidence"}
        ),
        retrieval=frozenset({"current_memory", "current_material"}),
    ),
    "consider_web_evidence": _profile(
        "consider_web_evidence",
        required=frozenset({"current_scene", "current_evidence"}),
        retrieval=frozenset({"current_memory", "current_material"}),
    ),
    "consider_codex_task": _profile(
        "consider_codex_task",
        required=frozenset(
            {"current_scene", "codex_task_source", "capability_catalog"}
        ),
        forbidden=_PRIVATE_RECALL,
    ),
    "consider_codex_result": _profile(
        "consider_codex_result",
        required=frozenset({"current_scene", "current_evidence", "capability_catalog"}),
        forbidden=_PRIVATE_RECALL,
    ),
    "consider_autonomous_life": _profile(
        "consider_autonomous_life",
        required=frozenset(
            {"current_life_opportunity", "life_mode", "current_activities"}
        ),
        retrieval=frozenset({"current_memory", "current_material"}),
    ),
    "consider_activity_attention": _profile(
        "consider_activity_attention",
        required=frozenset({"resource_snapshot", "current_activity"}),
        retrieval=frozenset({"current_memory", "current_material"}),
    ),
    "consider_activity_internal_work": _profile(
        "consider_activity_internal_work",
        required=frozenset({"resource_snapshot", "current_activity"}),
        retrieval=frozenset({"current_memory", "current_material"}),
    ),
    "consider_sleep": _profile(
        "consider_sleep",
        required=frozenset(
            {"current_maintenance_window", "life_mode", "current_activities"}
        ),
        forbidden=_PRIVATE_RECALL,
    ),
    "consider_life_query_result": _profile(
        "consider_life_query_result",
        required=frozenset(
            {"current_scene", "current_relationship", "current_evidence"}
        ),
        forbidden=_PRIVATE_RECALL,
    ),
    "maintain_subjective_memory": _profile(
        "maintain_subjective_memory",
        required=frozenset({"current_maintenance_phase"}),
        forbidden=frozenset({"current_material", "recall_status"}),
    ),
    "perform_subject_self_check": _profile(
        "perform_subject_self_check",
        required=frozenset({"current_maintenance_phase", "current_activities"}),
        forbidden=_PRIVATE_RECALL,
    ),
    "consider_creator_outreach": _profile(
        "consider_creator_outreach",
        required=frozenset(
            {"current_scene", "current_relationship", "current_evidence"}
        ),
        retrieval=frozenset({"current_memory", "current_material"}),
    ),
    "consider_other_human_input": _profile(
        "consider_other_human_input",
        required=frozenset(
            {"current_scene", "current_relationship", "current_evidence"}
        ),
        forbidden=frozenset({"creator_prompt"}) | _PRIVATE_RECALL | _PRIVATE_LIFE,
    ),
}


def context_profile(purpose: str) -> ContextAssemblyProfile:
    try:
        return _PROFILES[purpose]
    except KeyError:
        raise ContextViolation("CTX-PURPOSE") from None


__all__ = (
    "ContextAssemblyProfile",
    "ContextItemPolicy",
    "context_profile",
)
