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
autonomy_plans
accepted_experiences activities
activity_revisions
artifact_object_deletions artifact_objects artifact_publications artifacts audit_events
codex_task_sources

cognition_maintenance_cursors cognitive_attempts
cognitive_context_items cognitive_episodes
context_embedding_coverage
context_embedding_projections context_embedding_source_sets creator_exports managed_data_snapshot_parties
data_rights_order_items
data_rights_order_retry_attempts data_rights_orders
durable_work effect_attempts effect_observations
 effects
experience_evidence_links
external_channel_bindings
external_evidence external_message_parts interaction_scenes
life_material_revisions life_materials live_vision_observation_frames
live_vision_observations live_vision_sessions
live_voice_sessions
live_voice_turns
maintenance_session_revisions maintenance_sessions memory_relations
mood_appraisal_events mood_revisions
opportunities parties
party_input_interactions prompt_documents
prompt_revisions relationship_experience_links relationship_revisions
relationships runtime_instances
scene_participants
scene_timeline_items subject_commits
mind_revisions subject_component_revisions subjective_memories subjective_memory_revisions
subjects

"""

_RUNTIME_UPDATE = """
mood_revisions
codex_task_sources
maintenance_session_revisions
autonomy_plans
accepted_experiences activities
activity_revisions
artifact_object_deletions artifact_objects artifact_publications artifacts

 cognition_maintenance_cursors cognitive_attempts
cognitive_episodes
context_embedding_coverage context_embedding_source_sets creator_exports

data_rights_order_items data_rights_orders durable_work effect_attempts
 effects
external_channel_bindings
external_evidence external_message_parts
interaction_scenes life_material_revisions life_materials live_vision_observation_frames
live_vision_observations live_vision_sessions
live_voice_sessions
live_voice_turns maintenance_sessions mood_appraisal_events
opportunities parties party_input_interactions
  prompt_documents relationship_revisions relationships
runtime_instances
scene_participants mind_revisions subject_component_revisions
subjective_memories subjective_memory_revisions subjects

"""

_ADMIN_INSERT = """
admin_data_changes
deployment_environments durable_work effect_observations mood_revisions
mind_revisions subject_component_revisions
artifact_object_deletions artifact_objects artifact_publications artifacts
"""

_ADMIN_UPDATE = """
mind_revisions mood_revisions subject_component_revisions
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
