"""Current PostgreSQL table-level data-modification capabilities."""

from __future__ import annotations

from typing import Final, Literal

from armi_postgresql_contract.table_policy import TABLE_OWNERSHIP

DatabaseOperation = Literal["DELETE", "INSERT", "UPDATE"]
DatabaseDmlCapability = tuple[str, str, DatabaseOperation]


def _capabilities(
    role: str, operation: DatabaseOperation, tables: str
) -> frozenset[DatabaseDmlCapability]:
    return frozenset((role, table, operation) for table in tables.split() if table)


_RUNTIME_INSERT = """
event_appraisals
autonomy_plans
accepted_experiences
activity_revisions
artifact_object_deletions artifact_objects artifact_publications artifacts audit_events
codex_task_sources

 cognitive_attempts
 cognitive_episodes
context_embedding_coverage
context_embedding_projections context_embedding_source_sets creator_exports
data_rights_order_items
 data_rights_orders
durable_work effect_attempts effect_observations
 effects

external_channel_bindings
external_evidence external_message_parts interaction_scenes
life_material_revisions
live_vision_observations

live_voice_turns
 maintenance_sessions
 mood_revisions
opportunities parties
party_input_interactions
prompt_revisions  relationship_revisions
 runtime_instances

scene_timeline_items
mind_revisions focus_revisions subject_component_revisions  subjective_memory_revisions
subjects

"""

_RUNTIME_UPDATE = """
event_appraisals
mood_revisions
codex_task_sources

autonomy_plans
accepted_experiences
activity_revisions
artifact_object_deletions artifact_objects artifact_publications artifacts

  cognitive_attempts
cognitive_episodes
context_embedding_coverage context_embedding_source_sets creator_exports

data_rights_order_items data_rights_orders durable_work effect_attempts
 effects
external_channel_bindings
external_evidence external_message_parts
interaction_scenes life_material_revisions
live_vision_observations

live_voice_turns maintenance_sessions
opportunities parties party_input_interactions
  prompt_revisions relationship_revisions
runtime_instances
 mind_revisions focus_revisions subject_component_revisions
 subjective_memory_revisions subjects

"""

_ADMIN_INSERT = """
admin_data_changes
deployment_environments durable_work effect_observations mood_revisions
mind_revisions focus_revisions subject_component_revisions
artifact_object_deletions artifact_objects artifact_publications artifacts
"""

_ADMIN_UPDATE = """
mind_revisions focus_revisions mood_revisions subject_component_revisions
durable_work effects runtime_instances
subjects artifact_object_deletions artifact_objects
artifact_publications artifacts
"""

_ADMIN_DELETE = """
artifacts audit_events
external_evidence external_message_parts opportunities
party_input_interactions scene_timeline_items
"""

CURRENT_DML_CAPABILITIES: Final[frozenset[DatabaseDmlCapability]] = frozenset[
    DatabaseDmlCapability
]().union(
    _capabilities("armi_runtime", "INSERT", _RUNTIME_INSERT),
    _capabilities("armi_runtime", "UPDATE", _RUNTIME_UPDATE),
    _capabilities("armi_runtime", "DELETE", "context_embedding_projections"),
    _capabilities("armi_admin", "INSERT", _ADMIN_INSERT),
    _capabilities("armi_admin", "UPDATE", _ADMIN_UPDATE),
    _capabilities("armi_admin", "DELETE", _ADMIN_DELETE),
    frozenset(
        ("armi_admin", table, operation)
        for table, policy in TABLE_OWNERSHIP.items()
        if policy.maintenance_writable
        for operation in ("INSERT", "UPDATE", "DELETE")
    ),
)

CURRENT_COLUMN_DML_CAPABILITIES: Final = frozenset(
    ("armi_runtime", "deployment_environments", "UPDATE", column)
    for column in ("identity_key_digest", "identity_key_bound_at")
)

__all__ = (
    "CURRENT_COLUMN_DML_CAPABILITIES",
    "CURRENT_DML_CAPABILITIES",
    "DatabaseDmlCapability",
    "DatabaseOperation",
)
