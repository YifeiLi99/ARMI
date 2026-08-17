"""Construct the fixed owner participant roster exactly once per Runtime."""

from __future__ import annotations

from dataclasses import dataclass

from armi_activity.bootstrap import (
    bootstrap_activity_data_rights,
    bootstrap_activity_recovery,
)
from armi_attention.bootstrap import (
    bootstrap_opportunity_data_rights,
    bootstrap_opportunity_recovery,
)
from armi_capability.bootstrap import (
    bootstrap_capability_data_rights,
    bootstrap_capability_recovery,
)
from armi_codex.bootstrap import bootstrap_codex_data_rights, bootstrap_codex_recovery
from armi_cognition.bootstrap import (
    bootstrap_cognition_data_rights,
    bootstrap_cognition_recovery,
)
from armi_context.bootstrap import (
    bootstrap_context_data_rights,
    bootstrap_context_recovery,
)
from armi_data_rights.api import DataRightsParticipant
from armi_data_rights.bootstrap import bootstrap_data_rights_recovery
from armi_effect.bootstrap import (
    bootstrap_effect_data_rights,
    bootstrap_effect_recovery,
)
from armi_evidence.bootstrap import (
    bootstrap_evidence_data_rights,
    bootstrap_evidence_recovery,
)
from armi_experience.bootstrap import (
    bootstrap_experience_data_rights,
    bootstrap_experience_recovery,
)
from armi_expression.bootstrap import (
    bootstrap_expression_data_rights,
    bootstrap_expression_recovery,
)
from armi_interaction.bootstrap import (
    bootstrap_interaction_data_rights,
    bootstrap_interaction_recovery,
)
from armi_material.bootstrap import (
    bootstrap_material_data_rights,
    bootstrap_material_recovery,
)
from armi_memory.bootstrap import (
    bootstrap_memory_data_rights,
    bootstrap_memory_recovery,
)
from armi_mood.api import MoodReadPort
from armi_mood.bootstrap import bootstrap_mood_data_rights, bootstrap_mood_recovery
from armi_perception.bootstrap import (
    bootstrap_perception_data_rights,
    bootstrap_perception_recovery,
)
from armi_prompt.api import PromptReadPort
from armi_prompt.bootstrap import (
    bootstrap_prompt_data_rights,
    bootstrap_prompt_recovery,
)
from armi_relationship.bootstrap import (
    bootstrap_relationship_data_rights,
    bootstrap_relationship_recovery,
)
from armi_runtime_foundation import RecoveryOwnerIdentity, RecoveryParticipant
from armi_sleep.bootstrap import bootstrap_sleep_data_rights, bootstrap_sleep_recovery
from armi_subject_state.api import SubjectStateReadPort
from armi_subject_state.bootstrap import (
    bootstrap_subject_state_data_rights,
    bootstrap_subject_state_recovery,
)
from armi_web_observation.bootstrap import (
    bootstrap_web_observation_data_rights,
    bootstrap_web_observation_recovery,
)


@dataclass(frozen=True, slots=True)
class OwnerParticipantAggregate:
    owner: str
    data_rights: DataRightsParticipant
    recovery: RecoveryParticipant


@dataclass(frozen=True, slots=True)
class RuntimeOwnerRoster:
    owners: tuple[OwnerParticipantAggregate, ...]

    @property
    def data_rights(self) -> tuple[DataRightsParticipant, ...]:
        return tuple(owner.data_rights for owner in self.owners)

    @property
    def recovery(self) -> tuple[RecoveryParticipant, ...]:
        by_owner = {owner.owner: owner.recovery for owner in self.owners}
        return tuple(by_owner[owner] for owner in _RECOVERY_ORDER)

    @property
    def expected_recovery_owners(self) -> tuple[RecoveryOwnerIdentity, ...]:
        return tuple(RecoveryOwnerIdentity(owner) for owner in _RECOVERY_ORDER)


_DATA_RIGHTS_ORDER = (
    "interaction",
    "perception",
    "evidence",
    "opportunity",
    "experience",
    "cognition",
    "memory",
    "relationship",
    "activity",
    "material",
    "subject-state",
    "mood",
    "prompt",
    "sleep",
    "expression",
    "capability",
    "effect",
    "web-observation",
    "codex",
    "context",
    "data-rights",
)

_RECOVERY_ORDER = (
    "subject-state",
    "mood",
    "prompt",
    "activity",
    "material",
    "memory",
    "relationship",
    "sleep",
    "context",
    "interaction",
    "perception",
    "evidence",
    "cognition",
    "experience",
    "opportunity",
    "expression",
    "capability",
    "effect",
    "web-observation",
    "codex",
    "data-rights",
)


def compose_runtime_owner_roster(
    *,
    data_rights: DataRightsParticipant,
    mood_read: MoodReadPort,
    prompt_read: PromptReadPort,
    subject_state_read: SubjectStateReadPort,
) -> RuntimeOwnerRoster:
    recovery = {
        "interaction": bootstrap_interaction_recovery(),
        "perception": bootstrap_perception_recovery(),
        "evidence": bootstrap_evidence_recovery(),
        "opportunity": bootstrap_opportunity_recovery(),
        "experience": bootstrap_experience_recovery(),
        "cognition": bootstrap_cognition_recovery(),
        "memory": bootstrap_memory_recovery(),
        "relationship": bootstrap_relationship_recovery(),
        "activity": bootstrap_activity_recovery(),
        "material": bootstrap_material_recovery(),
        "subject-state": bootstrap_subject_state_recovery(subject_state_read),
        "mood": bootstrap_mood_recovery(mood_read),
        "prompt": bootstrap_prompt_recovery(prompt_read),
        "sleep": bootstrap_sleep_recovery(),
        "expression": bootstrap_expression_recovery(),
        "capability": bootstrap_capability_recovery(),
        "effect": bootstrap_effect_recovery(),
        "web-observation": bootstrap_web_observation_recovery(),
        "codex": bootstrap_codex_recovery(),
        "context": bootstrap_context_recovery(),
        "data-rights": bootstrap_data_rights_recovery(),
    }
    data_rights_participants = {
        "interaction": bootstrap_interaction_data_rights(),
        "perception": bootstrap_perception_data_rights(),
        "evidence": bootstrap_evidence_data_rights(),
        "opportunity": bootstrap_opportunity_data_rights(),
        "experience": bootstrap_experience_data_rights(),
        "cognition": bootstrap_cognition_data_rights(),
        "memory": bootstrap_memory_data_rights(),
        "relationship": bootstrap_relationship_data_rights(),
        "activity": bootstrap_activity_data_rights(),
        "material": bootstrap_material_data_rights(),
        "subject-state": bootstrap_subject_state_data_rights(),
        "mood": bootstrap_mood_data_rights(),
        "prompt": bootstrap_prompt_data_rights(),
        "sleep": bootstrap_sleep_data_rights(),
        "expression": bootstrap_expression_data_rights(),
        "capability": bootstrap_capability_data_rights(),
        "effect": bootstrap_effect_data_rights(),
        "web-observation": bootstrap_web_observation_data_rights(),
        "codex": bootstrap_codex_data_rights(),
        "context": bootstrap_context_data_rights(),
        "data-rights": data_rights,
    }
    owners = tuple(
        OwnerParticipantAggregate(
            owner,
            data_rights_participants[owner],
            recovery[owner],
        )
        for owner in _DATA_RIGHTS_ORDER
    )
    if tuple(owner.owner for owner in owners) != _DATA_RIGHTS_ORDER:
        raise RuntimeError("RUNTIME-OWNER-ROSTER")
    return RuntimeOwnerRoster(owners)


__all__ = (
    "OwnerParticipantAggregate",
    "RuntimeOwnerRoster",
    "compose_runtime_owner_roster",
)
