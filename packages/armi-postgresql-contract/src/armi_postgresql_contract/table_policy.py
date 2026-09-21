"""Packaged table ownership and explicit physical maintenance permissions.

Every baseline table must be listed. Views and Alembic identity are read-only.
Maintenance permissions never imply online owner semantics.
"""

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TableOwnership:
    owner: str
    maintenance_writable: bool
    pending_removal: bool = False


TABLE_OWNERSHIP: Mapping[str, TableOwnership] = {
    # Runtime/Foundation facts.
    "admin_data_changes": TableOwnership("runtime", maintenance_writable=False),
    "audit_events": TableOwnership("runtime", maintenance_writable=False),
    "deployment_environments": TableOwnership("runtime", maintenance_writable=False),
    "durable_work": TableOwnership("runtime", maintenance_writable=True),
    "life_generations": TableOwnership("runtime", maintenance_writable=False),
    "runtime_bundle_activations": TableOwnership("runtime", maintenance_writable=False),
    "runtime_instances": TableOwnership("runtime", maintenance_writable=False),
    "runtime_recovery_runs": TableOwnership("runtime", maintenance_writable=True),
    "schema_baseline_identity": TableOwnership("runtime", maintenance_writable=False),
    "subject_commits": TableOwnership("runtime", maintenance_writable=False),
    "subjects": TableOwnership("runtime", maintenance_writable=False),
    # Technical artifact catalog.
    "artifact_object_deletions": TableOwnership(
        "artifact-store", maintenance_writable=False
    ),
    "artifact_objects": TableOwnership("artifact-store", maintenance_writable=False),
    "artifact_publications": TableOwnership(
        "artifact-store", maintenance_writable=False
    ),
    "artifacts": TableOwnership("artifact-store", maintenance_writable=False),
    # Interaction.
    "external_channel_bindings": TableOwnership(
        "interaction", maintenance_writable=False
    ),
    "external_message_parts": TableOwnership("interaction", maintenance_writable=True),
    "interaction_scenes": TableOwnership("interaction", maintenance_writable=True),
    "parties": TableOwnership("interaction", maintenance_writable=False),
    "party_input_interactions": TableOwnership(
        "interaction", maintenance_writable=True
    ),
    "scene_participants": TableOwnership("interaction", maintenance_writable=False),
    "scene_timeline_items": TableOwnership("interaction", maintenance_writable=True),
    "system_notifications": TableOwnership("interaction", maintenance_writable=False),
    # Local real-time voice custody.
    "live_voice_sessions": TableOwnership("live-voice", maintenance_writable=True),
    "live_voice_turns": TableOwnership("live-voice", maintenance_writable=True),
    "live_voice_text_fragments": TableOwnership(
        "live-voice", maintenance_writable=True
    ),
    "live_voice_provider_attempts": TableOwnership(
        "live-voice", maintenance_writable=False
    ),
    "live_voice_playback_attempts": TableOwnership(
        "live-voice", maintenance_writable=True
    ),
    # Persistent local camera observation custody.
    "live_vision_sessions": TableOwnership("live-vision", maintenance_writable=True),
    "live_vision_observations": TableOwnership(
        "live-vision", maintenance_writable=True
    ),
    "live_vision_observation_frames": TableOwnership(
        "live-vision", maintenance_writable=True
    ),
    # Perception and evidence.
    "external_content_recognition_attempts": TableOwnership(
        "perception", maintenance_writable=False
    ),
    "visual_recognition_attempts": TableOwnership(
        "perception", maintenance_writable=False
    ),
    "experience_evidence_links": TableOwnership("evidence", maintenance_writable=True),
    "external_evidence": TableOwnership("evidence", maintenance_writable=True),
    # Attention and context.
    "opportunities": TableOwnership("attention", maintenance_writable=True),
    "autonomy_plans": TableOwnership("attention", maintenance_writable=False),
    "cognitive_context_dependencies": TableOwnership(
        "context", maintenance_writable=True
    ),
    "cognitive_context_items": TableOwnership("context", maintenance_writable=True),
    "context_embedding_attempts": TableOwnership("context", maintenance_writable=True),
    "context_embedding_coverage": TableOwnership("context", maintenance_writable=True),
    "context_embedding_projections": TableOwnership(
        "context", maintenance_writable=True
    ),
    "context_embedding_source_sets": TableOwnership(
        "context", maintenance_writable=True
    ),
    # Experience and cognition.
    "accepted_experiences": TableOwnership("experience", maintenance_writable=True),
    "cognitive_attempts": TableOwnership("cognition", maintenance_writable=False),
    "cognitive_candidate_applications": TableOwnership(
        "cognition", maintenance_writable=True
    ),
    "cognitive_candidate_basis_links": TableOwnership(
        "cognition", maintenance_writable=True
    ),
    "cognitive_candidate_validation_items": TableOwnership(
        "cognition", maintenance_writable=True
    ),
    "cognitive_candidate_validations": TableOwnership(
        "cognition", maintenance_writable=True
    ),
    "cognitive_episodes": TableOwnership("cognition", maintenance_writable=True),
    "cognition_maintenance_batch_sources": TableOwnership(
        "cognition", maintenance_writable=True
    ),
    "cognition_maintenance_batches": TableOwnership(
        "cognition", maintenance_writable=True
    ),
    "cognition_maintenance_cursors": TableOwnership(
        "cognition", maintenance_writable=True
    ),
    "exact_life_query_intents": TableOwnership("cognition", maintenance_writable=True),
    # Subject-owned components.
    "subject_component_heads": TableOwnership(
        "subject-state", maintenance_writable=True
    ),
    "subject_component_revisions": TableOwnership(
        "subject-state", maintenance_writable=True
    ),
    "prompt_documents": TableOwnership("prompt", maintenance_writable=True),
    "prompt_revisions": TableOwnership("prompt", maintenance_writable=True),
    "mind_heads": TableOwnership("mind", maintenance_writable=True),
    "mind_revisions": TableOwnership("mind", maintenance_writable=True),
    "mood_heads": TableOwnership("mood", maintenance_writable=True),
    "mood_revisions": TableOwnership("mood", maintenance_writable=True),
    "mood_appraisal_events": TableOwnership("mood", maintenance_writable=True),
    # Life facts.
    "memory_relations": TableOwnership("memory", maintenance_writable=True),
    "subjective_memories": TableOwnership("memory", maintenance_writable=True),
    "subjective_memory_revisions": TableOwnership("memory", maintenance_writable=True),
    "relationship_experience_links": TableOwnership(
        "relationship", maintenance_writable=True
    ),
    "relationship_revisions": TableOwnership("relationship", maintenance_writable=True),
    "relationships": TableOwnership("relationship", maintenance_writable=True),
    "life_material_revisions": TableOwnership("material", maintenance_writable=True),
    "life_materials": TableOwnership("material", maintenance_writable=True),
    "activities": TableOwnership("activity", maintenance_writable=True),
    "activity_decisions": TableOwnership("activity", maintenance_writable=True),
    "activity_revisions": TableOwnership("activity", maintenance_writable=True),
    "maintenance_phase_results": TableOwnership("sleep", maintenance_writable=True),
    "maintenance_session_revisions": TableOwnership("sleep", maintenance_writable=True),
    "maintenance_sessions": TableOwnership("sleep", maintenance_writable=True),
    "sleep_decisions": TableOwnership("sleep", maintenance_writable=True),
    # Expression, capability, and effect lifecycle.
    "action_intents": TableOwnership("expression", maintenance_writable=True),
    "dialogue_decisions": TableOwnership("expression", maintenance_writable=True),
    "capabilities": TableOwnership("capability", maintenance_writable=False),
    "effect_attempts": TableOwnership("effect", maintenance_writable=False),
    "effect_observations": TableOwnership("effect", maintenance_writable=False),
    "effect_outbox_items": TableOwnership("effect", maintenance_writable=False),
    "effects": TableOwnership("effect", maintenance_writable=False),
    "local_inbox_deliveries": TableOwnership("effect", maintenance_writable=False),
    # Web, Codex, and Data Rights.
    "observation_attempts": TableOwnership(
        "web-observation", maintenance_writable=False
    ),
    "observation_tool_calls": TableOwnership(
        "web-observation", maintenance_writable=True
    ),
    "web_evidence_sources": TableOwnership(
        "web-observation", maintenance_writable=True
    ),
    "web_observation_requests": TableOwnership(
        "web-observation", maintenance_writable=True
    ),
    "web_research_intents": TableOwnership(
        "web-observation", maintenance_writable=True
    ),
    "codex_task_sources": TableOwnership("codex", maintenance_writable=True),
    "codex_verification_results": TableOwnership("codex", maintenance_writable=False),
    "creator_exports": TableOwnership("data-rights", maintenance_writable=False),
    "managed_data_snapshot_parties": TableOwnership(
        "data-rights", maintenance_writable=False
    ),
    "managed_data_snapshots": TableOwnership("data-rights", maintenance_writable=False),
    "data_rights_party_fences": TableOwnership(
        "data-rights", maintenance_writable=False
    ),
    "data_rights_identity_keys": TableOwnership(
        "data-rights", maintenance_writable=False
    ),
    "data_rights_order_items": TableOwnership(
        "data-rights", maintenance_writable=False
    ),
    "data_rights_order_retry_attempts": TableOwnership(
        "data-rights", maintenance_writable=False
    ),
    "data_rights_orders": TableOwnership("data-rights", maintenance_writable=False),
}
