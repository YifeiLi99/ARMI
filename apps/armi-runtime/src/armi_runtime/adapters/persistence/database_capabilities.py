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
accepted_experiences action_intents activities
activity_decisions activity_revisions
artifact_object_deletions artifact_objects artifact_publications artifacts audit_events
codex_task_sources codex_verification_results
cognition_maintenance_batch_sources cognition_maintenance_batches
cognition_maintenance_cursors cognitive_attempts
cognitive_context_dependencies cognitive_context_items cognitive_episodes
context_embedding_coverage
context_embedding_projections context_embedding_source_sets creator_exports managed_data_snapshot_parties
managed_data_snapshots data_rights_order_items
data_rights_identity_keys data_rights_party_fences data_rights_order_retry_attempts data_rights_orders
dialogue_decisions durable_work effect_attempts effect_observations
effect_outbox_items  effects exact_life_query_intents
experience_evidence_links
external_channel_bindings
external_evidence external_message_parts interaction_scenes life_generations
life_material_revisions life_materials live_vision_observation_frames
live_vision_observations live_vision_sessions
live_voice_sessions
live_voice_turns local_inbox_deliveries
maintenance_session_revisions maintenance_sessions memory_relations
mood_appraisal_events mood_heads mood_revisions
opportunities parties
party_input_interactions prompt_documents
prompt_revisions relationship_experience_links relationship_revisions
relationships runtime_bundle_activations runtime_instances
scene_participants
scene_timeline_items sleep_decisions subject_commits mind_heads subject_component_heads
mind_revisions subject_component_revisions subjective_memories subjective_memory_revisions
subjects

"""

_RUNTIME_UPDATE = """
maintenance_session_revisions
autonomy_plans
accepted_experiences activities
activity_decisions activity_revisions
artifact_object_deletions artifact_objects artifact_publications artifacts
 cognition_maintenance_batch_sources
cognition_maintenance_batches cognition_maintenance_cursors cognitive_attempts
cognitive_episodes
context_embedding_coverage context_embedding_source_sets creator_exports
managed_data_snapshots
data_rights_party_fences data_rights_order_items data_rights_orders dialogue_decisions durable_work effect_attempts
effect_outbox_items  effects exact_life_query_intents
external_channel_bindings
external_evidence external_message_parts
interaction_scenes life_material_revisions life_materials live_vision_observation_frames
live_vision_observations live_vision_sessions
live_voice_sessions
live_voice_turns local_inbox_deliveries maintenance_sessions mood_appraisal_events mood_heads
opportunities parties party_input_interactions
  prompt_documents relationship_revisions relationships
runtime_instances
scene_participants mind_heads subject_component_heads mind_revisions subject_component_revisions
subjective_memories subjective_memory_revisions subjects

"""

_ADMIN_INSERT = """
admin_data_changes
deployment_environments durable_work effect_observations mood_revisions
mind_revisions subject_component_revisions
artifact_object_deletions artifact_objects artifact_publications artifacts
"""

_ADMIN_UPDATE = """
durable_work effect_outbox_items effects mood_heads runtime_instances
mind_heads subject_component_heads subjects artifact_object_deletions artifact_objects
artifact_publications artifacts
"""

_ADMIN_DELETE = """
artifacts audit_events dialogue_decisions
external_evidence external_message_parts local_inbox_deliveries opportunities
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

__all__ = (
    "CURRENT_DML_CAPABILITIES",
    "DatabaseDmlCapability",
    "DatabaseOperation",
)
