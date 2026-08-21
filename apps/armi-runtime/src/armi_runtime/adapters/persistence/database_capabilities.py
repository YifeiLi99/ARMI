"""Current PostgreSQL table-level data-modification capabilities."""

from __future__ import annotations

from typing import Final, Literal

DatabaseOperation = Literal["DELETE", "INSERT", "UPDATE"]
DatabaseDmlCapability = tuple[str, str, DatabaseOperation]


def _capabilities(
    role: str, operation: DatabaseOperation, tables: str
) -> frozenset[DatabaseDmlCapability]:
    return frozenset((role, table, operation) for table in tables.split() if table)


_RUNTIME_INSERT = """
accepted_experiences action_intent_revisions action_intents activities
activity_decisions activity_revisions artifacts audit_events
capability_request_basis_links capability_request_decisions capability_requests
codex_result_sources codex_task_sources codex_verification_results
cognition_maintenance_batch_sources cognition_maintenance_batches
cognition_maintenance_cursors cognitive_attempts cognitive_branches
cognitive_candidate_applications cognitive_candidate_basis_links
cognitive_candidate_validation_items cognitive_candidate_validations
cognitive_context_items cognitive_dialogue_aggregates cognitive_episodes
context_embedding_attempts context_embedding_coverage
context_embedding_projections creator_exports deletion_items deletion_orders
dialogue_decisions durable_work effect_attempts effect_observations
effect_outbox_items effects exact_life_query_intents experience_evidence_links
external_channel_bindings external_content_recognition_attempts
external_evidence external_message_parts interaction_scenes life_generations
life_material_revisions life_materials live_vision_observation_frames
live_vision_observations live_vision_sessions live_voice_playback_attempts
live_voice_provider_attempts live_voice_sessions live_voice_text_fragments
live_voice_turns local_inbox_deliveries maintenance_phase_results
maintenance_session_revisions maintenance_sessions memory_relations
mood_appraisal_events mood_heads mood_revisions
observation_attempts observation_tool_calls opportunities parties
party_input_interactions permission_grants policy_decisions prompt_documents
prompt_revisions relationship_experience_links relationship_revisions
relationships runtime_bundle_activations runtime_instances
runtime_recovery_metrics runtime_recovery_runs scene_participants
scene_timeline_items sleep_decisions subject_commits subject_component_heads
subject_component_revisions subjective_memories subjective_memory_revisions
subjects visual_recognition_attempts web_evidence_sources
web_observation_requests web_research_intents
"""

_RUNTIME_UPDATE = """
action_intent_revisions action_intents activities activity_decisions artifacts
capability_requests cognition_maintenance_batch_sources
cognition_maintenance_batches cognition_maintenance_cursors cognitive_attempts
cognitive_branches cognitive_dialogue_aggregates cognitive_episodes
context_embedding_attempts context_embedding_coverage creator_exports
deletion_items deletion_orders dialogue_decisions durable_work effect_attempts
effect_outbox_items effects exact_life_query_intents external_channel_bindings
external_content_recognition_attempts external_evidence external_message_parts
interaction_scenes life_materials live_vision_observation_frames
live_vision_observations live_vision_sessions live_voice_playback_attempts
live_voice_provider_attempts live_voice_sessions live_voice_text_fragments
live_voice_turns local_inbox_deliveries maintenance_sessions mood_heads
observation_attempts opportunities parties party_input_interactions
permission_grants policy_decisions prompt_documents relationships
runtime_instances runtime_recovery_metrics runtime_recovery_runs
scene_participants subject_component_heads subjective_memories subjects
visual_recognition_attempts web_observation_requests web_research_intents
"""

_ADMIN_INSERT = """
deployment_environments durable_work effect_observations mood_revisions
subject_component_revisions
"""

_ADMIN_UPDATE = """
durable_work effect_outbox_items effects mood_heads runtime_instances
subject_component_heads subjects
"""

_ADMIN_DELETE = """
artifacts audit_events dialogue_decisions external_content_recognition_attempts
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
)

__all__ = (
    "CURRENT_DML_CAPABILITIES",
    "DatabaseDmlCapability",
    "DatabaseOperation",
)
