"""PostgreSQL 18.4 schema-governance gateway for the append-only manifest."""

from __future__ import annotations

import hashlib
import json
from contextlib import suppress
from dataclasses import dataclass
from importlib.resources import files
from typing import Any, Final, LiteralString, cast
from uuid import UUID

import psycopg
import rfc8785
from psycopg import sql

from armi_runtime.adapters.database_errors import (
    KNOWN_DATABASE_CODES,
    DatabaseViolation,
)

from .role_policy import PostgreSQLRolePolicyGateway

_RESOURCE_PACKAGE = "armi_runtime.composition.runtime_resources"
_SCHEMA_RESOURCE = "schema"
_APPLICATION_VERSION = "0.0.0"
_ADVISORY_LOCK: Final = 4_701_932_009
_EXPECTED_TABLE_COLUMNS: Final = {
    "schema_migrations": (
        ("version", "bigint", True),
        ("name", "text", True),
        ("sha256", "text", True),
        ("applied_at", "timestamp(6) with time zone", True),
        ("application_version", "text", True),
    ),
    "artifacts": (
        ("artifact_id", "uuid", True),
        ("content_digest", "text", True),
        ("media_type", "text", True),
        ("byte_size", "bigint", True),
        ("storage_locator", "text", True),
        ("logical_kind", "text", True),
        ("producer_kind", "text", True),
        ("producer_trace_id", "text", True),
        ("privacy_scope", "text", True),
        ("integrity_status", "text", True),
        ("retention_status", "text", True),
        ("created_at", "timestamp(6) with time zone", True),
        ("deleted_at", "timestamp(6) with time zone", False),
        ("schema_version", "smallint", True),
    ),
    "audit_events": (
        ("audit_event_id", "uuid", True),
        ("actor_kind", "text", True),
        ("actor_ref", "uuid", True),
        ("purpose", "text", True),
        ("operation", "text", True),
        ("target_kind", "text", True),
        ("target_ref", "uuid", True),
        ("result_status", "text", True),
        ("trace_id", "text", True),
        ("sensitivity", "text", True),
        ("subject_id", "uuid", False),
        ("request_kind", "text", False),
        ("request_ref", "uuid", False),
        ("before_version", "bigint", False),
        ("after_version", "bigint", False),
        ("request_digest", "text", False),
        ("response_digest", "text", False),
        ("artifact_digest", "text", False),
        ("details_digest", "text", False),
        ("policy_ref", "uuid", False),
        ("grant_ref", "uuid", False),
        ("bundle_digest", "text", False),
        ("error_category", "text", False),
        ("schema_version", "smallint", True),
        ("occurred_at", "timestamp(6) with time zone", True),
    ),
    "durable_work": (
        ("work_id", "uuid", True),
        ("work_kind", "text", True),
        ("owner_kind", "text", True),
        ("owner_ref", "uuid", True),
        ("subject_id", "uuid", False),
        ("idempotency_key", "text", True),
        ("payload_kind", "text", False),
        ("payload_ref", "uuid", False),
        ("payload_digest", "text", True),
        ("priority", "smallint", True),
        ("not_before", "timestamp(6) with time zone", True),
        ("deadline_at", "timestamp(6) with time zone", True),
        ("status", "text", True),
        ("max_attempts", "smallint", True),
        ("attempt_count", "smallint", True),
        ("current_attempt_id", "uuid", False),
        ("lease_owner", "uuid", False),
        ("lease_expires_at", "timestamp(6) with time zone", False),
        ("lease_token", "bigint", True),
        ("result_kind", "text", False),
        ("result_ref", "uuid", False),
        ("last_error_code", "text", False),
        ("trace_id", "text", True),
        ("schema_version", "smallint", True),
        ("created_at", "timestamp(6) with time zone", True),
        ("updated_at", "timestamp(6) with time zone", True),
    ),
    "outbox_items": (
        ("outbox_item_id", "uuid", True),
        ("work_id", "uuid", True),
        ("message_kind", "text", True),
        ("payload_digest", "text", True),
        ("status", "text", True),
        ("available_at", "timestamp(6) with time zone", True),
        ("claimed_by", "uuid", False),
        ("claim_expires_at", "timestamp(6) with time zone", False),
        ("claim_token", "bigint", True),
        ("attempt_count", "smallint", True),
        ("max_attempts", "smallint", True),
        ("last_error_code", "text", False),
        ("delivered_at", "timestamp(6) with time zone", False),
        ("trace_id", "text", True),
        ("schema_version", "smallint", True),
        ("created_at", "timestamp(6) with time zone", True),
        ("updated_at", "timestamp(6) with time zone", True),
    ),
    "subjects": (
        ("subject_id", "uuid", True),
        ("singleton_key", "smallint", True),
        ("birth_request_id", "uuid", True),
        ("birth_idempotency_key", "text", True),
        ("birth_manifest_digest", "text", True),
        ("current_generation_id", "uuid", True),
        ("current_bundle_activation_id", "uuid", True),
        ("subject_version", "bigint", True),
        ("state_epoch", "bigint", True),
        ("status", "text", True),
        ("born_at", "timestamp(6) with time zone", True),
    ),
    "life_generations": (
        ("life_generation_id", "uuid", True),
        ("subject_id", "uuid", True),
        ("generation_no", "bigint", True),
        ("status", "text", True),
        ("opened_subject_version", "bigint", True),
        ("closed_subject_version", "bigint", False),
        ("activation_reason", "text", True),
        ("created_at", "timestamp(6) with time zone", True),
    ),
    "parties": (
        ("party_id", "uuid", True),
        ("party_kind", "text", True),
        ("represented_subject_id", "uuid", False),
        ("display_label", "text", False),
        ("creator_role", "text", False),
        ("status", "text", True),
        ("created_at", "timestamp(6) with time zone", True),
    ),
    "runtime_bundle_activations": (
        ("bundle_activation_id", "uuid", True),
        ("subject_id", "uuid", True),
        ("bundle_version", "text", True),
        ("bundle_digest", "text", True),
        ("manifest_artifact_id", "uuid", True),
        ("schema_baseline_digest", "text", True),
        ("fixed_policy_digest", "text", True),
        ("fixed_prompt_set_digest", "text", True),
        ("creator_asset_digest", "text", True),
        ("model_binding", "text", False),
        ("status", "text", True),
        ("activated_at", "timestamp(6) with time zone", True),
        ("deactivated_at", "timestamp(6) with time zone", False),
        ("activated_by_party_id", "uuid", True),
    ),
    "prompt_documents": (
        ("prompt_document_id", "uuid", True),
        ("subject_id", "uuid", True),
        ("prompt_kind", "text", True),
        ("write_authority", "text", True),
        ("current_revision_id", "uuid", False),
        ("status", "text", True),
        ("created_at", "timestamp(6) with time zone", True),
    ),
    "prompt_revisions": (
        ("prompt_revision_id", "uuid", True),
        ("prompt_document_id", "uuid", True),
        ("revision_no", "bigint", True),
        ("previous_revision_id", "uuid", False),
        ("content_artifact_id", "uuid", True),
        ("content_digest", "text", True),
        ("author_party_id", "uuid", True),
        ("subject_commit_id", "uuid", False),
        ("change_reason", "text", True),
        ("activated_at", "timestamp(6) with time zone", True),
    ),
    "subject_component_revisions": (
        ("component_revision_id", "uuid", True),
        ("subject_id", "uuid", True),
        ("component_kind", "text", True),
        ("component_version", "bigint", True),
        ("previous_revision_id", "uuid", False),
        ("origin_kind", "text", True),
        ("origin_ref", "uuid", True),
        ("subject_commit_id", "uuid", False),
        ("semantic_payload", "jsonb", True),
        ("privacy_scope", "text", True),
        ("created_at", "timestamp(6) with time zone", True),
        ("proposal_ref", "text", False),
        ("semantic_digest", "text", False),
    ),
    "subject_component_heads": (
        ("subject_id", "uuid", True),
        ("component_kind", "text", True),
        ("current_revision_id", "uuid", True),
        ("component_version", "bigint", True),
    ),
    "runtime_instances": (
        ("runtime_instance_id", "uuid", True),
        ("subject_id", "uuid", True),
        ("life_generation_id", "uuid", True),
        ("bundle_activation_id", "uuid", True),
        ("fence_token", "bigint", True),
        ("status", "text", True),
        ("started_at", "timestamp(6) with time zone", True),
        ("last_heartbeat_at", "timestamp(6) with time zone", True),
        ("lease_expires_at", "timestamp(6) with time zone", True),
        ("stopped_at", "timestamp(6) with time zone", False),
        ("schema_version", "integer", True),
    ),
    "runtime_recovery_runs": (
        ("recovery_run_id", "uuid", True),
        ("runtime_instance_id", "uuid", True),
        ("subject_id", "uuid", True),
        ("life_generation_id", "uuid", True),
        ("bundle_activation_id", "uuid", True),
        ("fence_token", "bigint", True),
        ("status", "text", True),
        ("started_at", "timestamp(6) with time zone", True),
        ("completed_at", "timestamp(6) with time zone", False),
        ("requeued_work_count", "integer", True),
        ("terminal_work_count", "integer", True),
        ("requeued_outbox_count", "integer", True),
        ("dead_outbox_count", "integer", True),
        ("resumable_work_count", "integer", True),
        ("resumable_outbox_count", "integer", True),
        ("critical_artifact_count", "integer", True),
        ("blocker_count", "integer", True),
        ("summary_digest", "text", False),
        ("schema_version", "smallint", True),
        ("resumable_opportunity_count", "integer", True),
        ("resumable_cognitive_episode_count", "integer", True),
        ("resumable_model_attempt_count", "integer", True),
        ("resumable_candidate_validation_count", "integer", True),
        ("resumable_subject_commit_count", "integer", True),
        ("resumable_capability_request_count", "integer", True),
        ("resumable_response_operation_count", "integer", True),
    ),
    "interaction_scenes": (
        ("scene_id", "uuid", True),
        ("subject_id", "uuid", True),
        ("scene_key", "text", True),
        ("scene_kind", "text", True),
        ("primary_party_id", "uuid", True),
        ("audience_scope", "text", True),
        ("current_status", "text", True),
        ("opened_at", "timestamp(6) with time zone", True),
        ("closed_at", "timestamp(6) with time zone", False),
        ("recent_context_boundary", "uuid", False),
        ("schema_version", "smallint", True),
    ),
    "scene_timeline_items": (
        ("timeline_item_id", "uuid", True),
        ("scene_id", "uuid", True),
        ("source_kind", "text", True),
        ("source_ref", "uuid", True),
        ("source_event_no", "bigint", True),
        ("result_status", "text", True),
        ("occurred_at", "timestamp(6) with time zone", True),
        ("recorded_at", "timestamp(6) with time zone", True),
        ("schema_version", "smallint", True),
    ),
    "creator_input_interactions": (
        ("creator_interaction_id", "uuid", True),
        ("subject_id", "uuid", True),
        ("scene_id", "uuid", True),
        ("creator_party_id", "uuid", True),
        ("purpose", "text", True),
        ("idempotency_key", "text", True),
        ("request_digest", "text", True),
        ("content_digest", "text", True),
        ("trace_id", "text", True),
        ("received_at", "timestamp(6) with time zone", True),
        ("schema_version", "smallint", True),
    ),
    "external_evidence": (
        ("evidence_id", "uuid", True),
        ("creator_interaction_id", "uuid", True),
        ("subject_id", "uuid", True),
        ("scene_id", "uuid", True),
        ("creator_party_id", "uuid", True),
        ("artifact_id", "uuid", True),
        ("source_kind", "text", True),
        ("trust_status", "text", True),
        ("privacy_scope", "text", True),
        ("acceptance_status", "text", True),
        ("received_at", "timestamp(6) with time zone", True),
        ("schema_version", "smallint", True),
    ),
    "opportunities": (
        ("opportunity_id", "uuid", True),
        ("evidence_id", "uuid", True),
        ("subject_id", "uuid", True),
        ("scene_id", "uuid", True),
        ("creator_party_id", "uuid", True),
        ("purpose", "text", True),
        ("eligibility_status", "text", True),
        ("current_disposition", "text", True),
        ("available_after", "timestamp(6) with time zone", True),
        ("expires_at", "timestamp(6) with time zone", False),
        ("schema_version", "smallint", True),
        ("selected_at", "timestamp(6) with time zone", False),
        ("root_opportunity_id", "uuid", True),
        ("predecessor_opportunity_id", "uuid", False),
        ("reconsideration_no", "smallint", True),
        ("resolved_at", "timestamp(6) with time zone", False),
    ),
    "cognitive_episodes": (
        ("cognitive_episode_id", "uuid", True),
        ("opportunity_id", "uuid", True),
        ("subject_id", "uuid", True),
        ("scene_id", "uuid", True),
        ("creator_party_id", "uuid", True),
        ("purpose", "text", True),
        ("status", "text", True),
        ("base_subject_version", "bigint", True),
        ("base_state_epoch", "bigint", True),
        ("bundle_activation_id", "uuid", True),
        ("policy_digest", "text", True),
        ("mechanism_identity", "text", True),
        ("mechanism_config_digest", "text", True),
        ("context_manifest_artifact_id", "uuid", False),
        ("compiled_context_artifact_id", "uuid", False),
        ("context_digest", "text", False),
        ("failure_code", "text", False),
        ("trace_id", "text", True),
        ("created_at", "timestamp(6) with time zone", True),
        ("prepared_at", "timestamp(6) with time zone", False),
        ("schema_version", "smallint", True),
        ("model_returned_at", "timestamp(6) with time zone", False),
        ("final_disposition", "text", False),
        ("validated_at", "timestamp(6) with time zone", False),
        ("application_resolution", "text", False),
        ("committed_at", "timestamp(6) with time zone", False),
    ),
    "cognitive_context_items": (
        ("context_item_id", "uuid", True),
        ("cognitive_episode_id", "uuid", True),
        ("ordinal", "smallint", True),
        ("section", "text", True),
        ("item_kind", "text", True),
        ("source_kind", "text", True),
        ("source_ref", "uuid", False),
        ("source_version", "bigint", False),
        ("source_digest", "text", False),
        ("trust_class", "text", True),
        ("privacy_scope", "text", True),
        ("disposition", "text", True),
        ("reason_code", "text", False),
        ("content_bytes", "integer", True),
        ("schema_version", "smallint", True),
    ),
    "cognitive_attempts": (
        ("model_attempt_id", "uuid", True),
        ("cognitive_episode_id", "uuid", True),
        ("work_id", "uuid", True),
        ("work_attempt_id", "uuid", True),
        ("attempt_no", "smallint", True),
        ("binding_digest", "text", True),
        ("provider", "text", True),
        ("model_id", "text", True),
        ("version_policy", "text", True),
        ("profile", "text", True),
        ("request_schema_version", "text", True),
        ("candidate_schema_version", "text", True),
        ("pricing_snapshot_id", "text", True),
        ("credential_identity", "text", True),
        ("request_artifact_id", "uuid", True),
        ("request_digest", "text", True),
        ("dispatch_status", "text", True),
        ("provider_request_id", "text", False),
        ("provider_model_id", "text", False),
        ("response_artifact_id", "uuid", False),
        ("input_tokens", "integer", False),
        ("output_tokens", "integer", False),
        ("cached_input_tokens", "integer", False),
        ("estimated_cost_microyuan", "bigint", False),
        ("result_status", "text", False),
        ("error_code", "text", False),
        ("prepared_at", "timestamp(6) with time zone", True),
        ("dispatched_at", "timestamp(6) with time zone", False),
        ("settled_at", "timestamp(6) with time zone", False),
        ("schema_version", "smallint", True),
    ),
    "cognitive_candidate_validations": (
        ("candidate_validation_id", "uuid", True),
        ("cognitive_episode_id", "uuid", True),
        ("model_attempt_id", "uuid", True),
        ("work_id", "uuid", True),
        ("subject_id", "uuid", True),
        ("life_generation_id", "uuid", True),
        ("bundle_activation_id", "uuid", True),
        ("base_subject_version", "bigint", True),
        ("base_state_epoch", "bigint", True),
        ("context_digest", "text", True),
        ("candidate_contract_version", "text", True),
        ("candidate_digest", "text", True),
        ("validator_identity", "text", True),
        ("policy_digest", "text", True),
        ("validation_status", "text", True),
        ("final_disposition", "text", False),
        ("change_set_artifact_id", "uuid", False),
        ("change_set_digest", "text", False),
        ("accepted_count", "smallint", True),
        ("rejected_count", "smallint", True),
        ("error_code", "text", False),
        ("validated_by_runtime_instance_id", "uuid", True),
        ("validation_fence_token", "bigint", True),
        ("validated_at", "timestamp(6) with time zone", True),
        ("schema_version", "smallint", True),
    ),
    "cognitive_candidate_validation_items": (
        ("candidate_validation_id", "uuid", True),
        ("proposal_ref", "text", True),
        ("atomic_group_ref", "text", True),
        ("owner_kind", "text", True),
        ("fact_class", "text", True),
        ("validation_status", "text", True),
        ("reason_code", "text", False),
        ("semantic_digest", "text", True),
        ("ordinal", "smallint", True),
        ("schema_version", "smallint", True),
    ),
    "cognitive_candidate_basis_links": (
        ("candidate_validation_id", "uuid", True),
        ("proposal_ref", "text", True),
        ("context_item_id", "uuid", True),
        ("ordinal", "smallint", True),
    ),
    "subject_commits": (
        ("subject_commit_id", "uuid", True),
        ("candidate_validation_id", "uuid", True),
        ("cognitive_episode_id", "uuid", True),
        ("subject_id", "uuid", True),
        ("life_generation_id", "uuid", True),
        ("bundle_activation_id", "uuid", True),
        ("base_subject_version", "bigint", True),
        ("new_subject_version", "bigint", True),
        ("base_state_epoch", "bigint", True),
        ("change_set_digest", "text", True),
        ("commit_digest", "text", True),
        ("runtime_instance_id", "uuid", True),
        ("fence_token", "bigint", True),
        ("trace_id", "text", True),
        ("committed_at", "timestamp(6) with time zone", True),
        ("schema_version", "smallint", True),
    ),
    "accepted_experiences": (
        ("experience_id", "uuid", True),
        ("subject_commit_id", "uuid", True),
        ("cognitive_episode_id", "uuid", True),
        ("proposal_ref", "text", True),
        ("experience_kind", "text", True),
        ("fact_class", "text", True),
        ("first_person_gist", "text", True),
        ("scene_id", "uuid", True),
        ("occurred_at", "timestamp(6) with time zone", True),
        ("learned_at", "timestamp(6) with time zone", True),
        ("accepted_at", "timestamp(6) with time zone", True),
        ("source_perspective", "text", True),
        ("uncertainty", "text", False),
        ("privacy_scope", "text", True),
        ("schema_version", "smallint", True),
    ),
    "experience_evidence_links": (
        ("experience_id", "uuid", True),
        ("evidence_id", "uuid", True),
        ("context_item_id", "uuid", True),
        ("link_kind", "text", True),
        ("ordinal", "smallint", True),
    ),
    "cognitive_candidate_applications": (
        ("candidate_application_id", "uuid", True),
        ("candidate_validation_id", "uuid", True),
        ("cognitive_episode_id", "uuid", True),
        ("work_id", "uuid", True),
        ("resolution", "text", True),
        ("subject_commit_id", "uuid", False),
        ("successor_opportunity_id", "uuid", False),
        ("base_subject_version", "bigint", True),
        ("observed_subject_version", "bigint", True),
        ("completion_digest", "text", True),
        ("runtime_instance_id", "uuid", True),
        ("fence_token", "bigint", True),
        ("resolved_at", "timestamp(6) with time zone", True),
        ("schema_version", "smallint", True),
    ),
    "capabilities": (
        ("capability_id", "uuid", True),
        ("capability_kind", "text", True),
        ("adapter_kind", "text", True),
        ("operation_class", "text", True),
        ("scope_schema", "text", True),
        ("availability_status", "text", True),
        ("verification_capability", "text", True),
        ("configuration_version", "bigint", True),
        ("configuration_digest", "text", True),
    ),
    "capability_requests": (
        ("capability_request_id", "uuid", True),
        ("subject_commit_id", "uuid", True),
        ("proposal_ref", "text", True),
        ("subject_id", "uuid", True),
        ("interaction_scene_id", "uuid", True),
        ("creator_party_id", "uuid", True),
        ("capability_id", "uuid", True),
        ("capability_kind", "text", True),
        ("operation_class", "text", True),
        ("audience_scope", "text", False),
        ("data_scope", "text", False),
        ("purpose", "text", True),
        ("workspace_scope", "text", False),
        ("artifact_scope", "text", False),
        ("network_access", "boolean", False),
        ("requested_valid_for_seconds", "integer", True),
        ("requested_max_uses", "integer", True),
        ("requested_max_payload_bytes", "integer", False),
        ("request_digest", "text", True),
        ("current_status", "text", True),
        ("request_version", "bigint", True),
        ("resolved_by_party_id", "uuid", False),
        ("resolution_reason_class", "text", False),
        ("resolved_at", "timestamp(6) with time zone", False),
        ("created_at", "timestamp(6) with time zone", True),
        ("schema_version", "smallint", True),
    ),
    "capability_request_basis_links": (
        ("capability_request_id", "uuid", True),
        ("context_item_id", "uuid", True),
        ("ordinal", "smallint", True),
    ),
    "capability_request_decisions": (
        ("capability_decision_id", "uuid", True),
        ("capability_request_id", "uuid", True),
        ("creator_party_id", "uuid", True),
        ("expected_request_version", "bigint", True),
        ("resulting_request_version", "bigint", True),
        ("decision_kind", "text", True),
        ("command_digest", "text", True),
        ("scope_digest", "text", False),
        ("reason_code", "text", False),
        ("decided_at", "timestamp(6) with time zone", True),
        ("schema_version", "smallint", True),
    ),
    "permission_grants": (
        ("grant_id", "uuid", True),
        ("capability_request_id", "uuid", True),
        ("creator_party_id", "uuid", True),
        ("capability_id", "uuid", True),
        ("subject_id", "uuid", True),
        ("interaction_scene_id", "uuid", True),
        ("operation_class", "text", True),
        ("audience_scope", "text", True),
        ("data_scope", "text", True),
        ("purpose", "text", True),
        ("valid_from", "timestamp(6) with time zone", True),
        ("valid_until", "timestamp(6) with time zone", True),
        ("max_uses", "integer", True),
        ("consumed_uses", "integer", True),
        ("max_payload_bytes", "integer", True),
        ("scope_digest", "text", True),
        ("status", "text", True),
        ("revoked_at", "timestamp(6) with time zone", False),
        ("schema_version", "smallint", True),
    ),
    "action_intents": (
        ("action_intent_id", "uuid", True),
        ("subject_id", "uuid", True),
        ("interaction_scene_id", "uuid", True),
        ("creator_party_id", "uuid", True),
        ("root_opportunity_id", "uuid", True),
        ("purpose", "text", True),
        ("current_revision_id", "uuid", False),
        ("created_at", "timestamp(6) with time zone", True),
        ("schema_version", "smallint", True),
    ),
    "action_intent_revisions": (
        ("action_intent_revision_id", "uuid", True),
        ("action_intent_id", "uuid", True),
        ("revision_no", "bigint", True),
        ("response_artifact_id", "uuid", True),
        ("response_digest", "text", True),
        ("response_bytes", "integer", True),
        ("media_type", "text", True),
        ("capability_kind", "text", True),
        ("operation_class", "text", True),
        ("audience_scope", "text", True),
        ("data_scope", "text", True),
        ("purpose", "text", True),
        ("candidate_validation_id", "uuid", True),
        ("proposal_ref", "text", True),
        ("subject_commit_id", "uuid", True),
        ("created_at", "timestamp(6) with time zone", True),
        ("schema_version", "smallint", True),
    ),
    "formal_no_action_decisions": (
        ("formal_no_action_id", "uuid", True),
        ("candidate_application_id", "uuid", True),
        ("candidate_validation_id", "uuid", True),
        ("proposal_ref", "text", True),
        ("root_opportunity_id", "uuid", True),
        ("decision_kind", "text", True),
        ("reason_class", "text", True),
        ("basis_digest", "text", True),
        ("decided_at", "timestamp(6) with time zone", True),
        ("schema_version", "smallint", True),
    ),
    "creator_response_operations": (
        ("creator_response_operation_id", "uuid", True),
        ("root_opportunity_id", "uuid", True),
        ("subject_id", "uuid", True),
        ("interaction_scene_id", "uuid", True),
        ("creator_party_id", "uuid", True),
        ("action_intent_id", "uuid", False),
        ("formal_no_action_id", "uuid", False),
        ("admission_work_id", "uuid", False),
        ("current_status", "text", True),
        ("matched_grant_id", "uuid", False),
        ("completion_digest", "text", False),
        ("reason_code", "text", False),
        ("created_at", "timestamp(6) with time zone", True),
        ("completed_at", "timestamp(6) with time zone", False),
        ("schema_version", "smallint", True),
    ),
}
_EXPECTED_CONSTRAINT_KINDS: Final = {
    "schema_migrations": tuple(sorted(("c", "c", "c", "n", "n", "n", "n", "n", "p"))),
    "artifacts": tuple(sorted((*("c",) * 13, *("n",) * 13, "p", "u", "u"))),
    "audit_events": tuple(sorted((*("c",) * 27, *("n",) * 12, "p"))),
    "durable_work": tuple(sorted((*("c",) * 26, *("n",) * 17, "p", "u"))),
    "outbox_items": tuple(sorted((*("c",) * 14, *("n",) * 13, "f", "p", "u"))),
    "subjects": tuple(
        sorted((*("c",) * 10, *("n",) * 11, *("f",) * 2, "p", *("u",) * 3))
    ),
    "life_generations": tuple(sorted((*("c",) * 6, *("n",) * 7, "f", "p", "u"))),
    "parties": tuple(sorted((*("c",) * 5, *("n",) * 4, "f", "p"))),
    "runtime_bundle_activations": tuple(
        sorted((*("c",) * 10, *("n",) * 12, *("f",) * 3, "p"))
    ),
    "prompt_documents": tuple(
        sorted((*("c",) * 6, *("n",) * 6, *("f",) * 2, "p", "u"))
    ),
    "prompt_revisions": tuple(
        sorted((*("c",) * 6, *("n",) * 8, *("f",) * 3, "p", "u"))
    ),
    "subject_component_revisions": tuple(
        sorted((*("c",) * 10, *("n",) * 9, *("f",) * 3, "p", "u"))
    ),
    "subject_component_heads": tuple(
        sorted((*("c",) * 2, *("n",) * 4, *("f",) * 2, "p"))
    ),
    "runtime_instances": tuple(
        sorted((*("c",) * 6, *("n",) * 10, *("f",) * 3, "p", "u"))
    ),
    "runtime_recovery_runs": tuple(
        sorted((*("c",) * 23, *("n",) * 24, *("f",) * 4, "p", "u"))
    ),
    "interaction_scenes": tuple(
        sorted((*("c",) * 8, *("n",) * 9, *("f",) * 2, "p", *("u",) * 2))
    ),
    "scene_timeline_items": tuple(sorted((*("c",) * 6, *("n",) * 9, "f", "p", "u"))),
    "creator_input_interactions": tuple(
        sorted((*("c",) * 7, *("n",) * 11, "f", "p", *("u",) * 2))
    ),
    "external_evidence": tuple(
        sorted((*("c",) * 6, *("n",) * 12, *("f",) * 2, "p", *("u",) * 2))
    ),
    "opportunities": tuple(
        sorted((*("c",) * 9, *("n",) * 12, *("f",) * 3, "p", *("u",) * 3))
    ),
    "cognitive_episodes": tuple(
        sorted((*("c",) * 15, *("n",) * 16, *("f",) * 4, "p", "u"))
    ),
    "cognitive_context_items": tuple(
        sorted((*("c",) * 16, *("n",) * 11, "f", "p", "u"))
    ),
    "cognitive_attempts": tuple(
        sorted((*("c",) * 23, *("n",) * 19, *("f",) * 4, "p", *("u",) * 2))
    ),
    "cognitive_candidate_validations": tuple(
        sorted((*("c",) * 17, *("n",) * 21, *("f",) * 8, "p", *("u",) * 3))
    ),
    "cognitive_candidate_validation_items": tuple(
        sorted((*("c",) * 10, *("n",) * 9, "f", "p", "u"))
    ),
    "cognitive_candidate_basis_links": tuple(
        sorted(("c", *("n",) * 4, *("f",) * 2, "p", "u"))
    ),
    "subject_commits": tuple(
        sorted((*("c",) * 9, *("n",) * 16, *("f",) * 6, "p", *("u",) * 3))
    ),
    "accepted_experiences": tuple(
        sorted((*("c",) * 9, *("n",) * 14, *("f",) * 3, "p", "u"))
    ),
    "experience_evidence_links": tuple(
        sorted((*("c",) * 2, *("n",) * 5, *("f",) * 3, "p", "u"))
    ),
    "cognitive_candidate_applications": tuple(
        sorted((*("c",) * 9, *("n",) * 12, *("f",) * 6, "p", *("u",) * 5))
    ),
    "capabilities": tuple(sorted((*("c",) * 6, *("n",) * 9, "p", "u"))),
    "capability_requests": tuple(
        sorted((*("c",) * 10, *("n",) * 17, *("f",) * 6, "p", "u"))
    ),
    "capability_request_basis_links": tuple(
        sorted(("c", *("n",) * 3, *("f",) * 2, "p", "u"))
    ),
    "capability_request_decisions": tuple(
        sorted((*("c",) * 6, *("n",) * 9, *("f",) * 2, "p", "u"))
    ),
    "permission_grants": tuple(
        sorted((*("c",) * 6, *("n",) * 18, *("f",) * 5, "p", "u"))
    ),
    "action_intents": tuple(sorted((*("c",) * 3, *("n",) * 8, *("f",) * 5, "p", "u"))),
    "action_intent_revisions": tuple(
        sorted((*("c",) * 12, *("n",) * 17, *("f",) * 4, "p", *("u",) * 3))
    ),
    "formal_no_action_decisions": tuple(
        sorted((*("c",) * 6, *("n",) * 10, *("f",) * 3, "p", *("u",) * 3))
    ),
    "creator_response_operations": tuple(
        sorted((*("c",) * 6, *("n",) * 8, *("f",) * 8, "p", *("u",) * 4))
    ),
}


@dataclass(frozen=True, slots=True)
class SchemaStatus:
    status: str
    target_version: int
    applied_version: int
    migration_set_sha256: str
    catalog_sha256: str | None
    role_policy_sha256: str | None = None
    privilege_catalog_sha256: str | None = None

    def safe_view(self) -> dict[str, object]:
        return {
            "status": self.status,
            "target_version": self.target_version,
            "applied_version": self.applied_version,
            "migration_set_sha256": self.migration_set_sha256,
            "catalog_sha256": self.catalog_sha256,
            "role_policy_sha256": self.role_policy_sha256,
            "privilege_catalog_sha256": self.privilege_catalog_sha256,
        }


@dataclass(frozen=True, slots=True)
class _PackagedSchema:
    manifest: dict[str, Any]
    migrations: tuple[tuple[int, str, str, bytes], ...]
    invariants: bytes


def _digest(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _load_packaged_schema() -> _PackagedSchema:
    root = files(_RESOURCE_PACKAGE).joinpath(_SCHEMA_RESOURCE)
    try:
        manifest_bytes = root.joinpath("manifests/schema-manifest.json").read_bytes()
        manifest = cast(dict[str, Any], json.loads(manifest_bytes))
    except OSError, UnicodeDecodeError, json.JSONDecodeError:
        raise DatabaseViolation(
            "DB-MANIFEST-DRIFT",
            "the packaged schema manifest is unavailable or malformed",
        ) from None
    if (
        manifest.get("schema_version") != "armi.schema-manifest.v1"
        or rfc8785.dumps(cast(Any, manifest)) + b"\n" != manifest_bytes
        or manifest.get("runtime_upgrade_allowed") is not False
    ):
        raise DatabaseViolation(
            "DB-MANIFEST-DRIFT", "the packaged schema manifest has drifted"
        )
    migrations: list[tuple[int, str, str, bytes]] = []
    expected_version = 1
    migration_set = bytearray()
    try:
        entries = cast(list[dict[str, Any]], manifest["migrations"])
        for entry in entries:
            version = int(entry["version"])
            name = str(entry["name"])
            path = str(entry["path"])
            declared_digest = str(entry["sha256"])
            if version != expected_version or not path.startswith("schema/migrations/"):
                raise DatabaseViolation(
                    "DB-SCHEMA-GAP", "the packaged migration sequence is not continuous"
                )
            value = root.joinpath(path.removeprefix("schema/")).read_bytes()
            if _digest(value) != declared_digest:
                raise DatabaseViolation(
                    "DB-SCHEMA-HASH", "a packaged migration digest does not match"
                )
            migration_set.extend(f"{version}\t{path}\t{declared_digest}\n".encode())
            migrations.append((version, name, declared_digest, value))
            expected_version += 1
        invariant_entry = cast(dict[str, Any], manifest["invariants"])
        invariant_path = str(invariant_entry["path"])
        invariants = root.joinpath(invariant_path.removeprefix("schema/")).read_bytes()
    except DatabaseViolation:
        raise
    except KeyError, TypeError, ValueError, OSError:
        raise DatabaseViolation(
            "DB-MANIFEST-DRIFT", "the packaged schema resource set is incomplete"
        ) from None
    if (
        _digest(bytes(migration_set)) != manifest.get("migration_set_sha256")
        or _digest(invariants) != invariant_entry.get("sha256")
        or int(cast(dict[str, Any], manifest.get("target", {})).get("version", 0))
        != len(migrations)
    ):
        raise DatabaseViolation(
            "DB-MANIFEST-DRIFT", "the packaged schema resource digest has drifted"
        )
    return _PackagedSchema(manifest, tuple(migrations), invariants)


class PostgreSQLSchemaGateway:
    """Validate and advance only the packaged schema migration set."""

    __slots__ = ("_packaged",)

    def __init__(self) -> None:
        self._packaged = _load_packaged_schema()

    @property
    def migration_set_sha256(self) -> str:
        return str(self._packaged.manifest["migration_set_sha256"])

    def status(
        self,
        conninfo: str,
        *,
        environment_id: UUID,
        role_class: str = "runtime",
    ) -> SchemaStatus:
        with self._connect(conninfo) as connection:
            self._verify_database_identity(connection)
            state = self._inspect_schema(connection, allow_empty=False)
            role_status = PostgreSQLRolePolicyGateway().verify(
                connection,
                environment_id=environment_id,
                role_class=role_class,
            )
            return SchemaStatus(
                state.status,
                state.target_version,
                state.applied_version,
                state.migration_set_sha256,
                state.catalog_sha256,
                role_status.role_policy_sha256,
                role_status.privilege_catalog_sha256,
            )

    def upgrade(self, conninfo: str, *, environment_id: UUID) -> SchemaStatus:
        with self._connect(conninfo, autocommit=True) as connection:
            self._verify_database_identity(connection)
            role_gateway = PostgreSQLRolePolicyGateway()
            role_gateway.verify(
                connection,
                environment_id=environment_id,
                role_class="migrator",
                require_objects=False,
            )
            try:
                connection.execute(
                    "SELECT pg_catalog.pg_advisory_lock(%s)", (_ADVISORY_LOCK,)
                )
            except psycopg.Error:
                raise DatabaseViolation(
                    "DB-MIGRATION-LOCK",
                    "the fixed schema migration lock could not be acquired",
                ) from None
            try:
                current = self._inspect_schema(connection, allow_empty=True)
                for version, name, digest, migration in self._packaged.migrations:
                    if version <= current.applied_version:
                        continue
                    try:
                        with connection.transaction():
                            connection.execute("SET LOCAL ROLE armi_owner")
                            connection.execute(
                                sql.SQL(cast(LiteralString, migration.decode("utf-8")))
                            )
                            connection.execute(
                                """
                                INSERT INTO armi.schema_migrations
                                    (version, name, sha256, application_version)
                                VALUES (%s, %s, %s, %s)
                                """,
                                (version, name, digest, _APPLICATION_VERSION),
                            )
                            current = self._inspect_schema(
                                connection,
                                allow_empty=True,
                            )
                    except UnicodeDecodeError, psycopg.Error:
                        raise DatabaseViolation(
                            "DB-MIGRATION-FAILED",
                            "the packaged migration failed and was rolled back",
                        ) from None
                role_status = role_gateway.verify(
                    connection,
                    environment_id=environment_id,
                    role_class="migrator",
                )
                return SchemaStatus(
                    current.status,
                    current.target_version,
                    current.applied_version,
                    current.migration_set_sha256,
                    current.catalog_sha256,
                    role_status.role_policy_sha256,
                    role_status.privilege_catalog_sha256,
                )
            finally:
                with suppress(psycopg.Error):
                    connection.execute(
                        "SELECT pg_catalog.pg_advisory_unlock(%s)", (_ADVISORY_LOCK,)
                    )

    def _connect(
        self, conninfo: str, *, autocommit: bool = False
    ) -> psycopg.Connection[tuple[Any, ...]]:
        try:
            return psycopg.connect(
                conninfo,
                autocommit=autocommit,
                connect_timeout=5,
                application_name="armi-schema-governance",
            )
        except psycopg.Error, UnicodeError, ValueError:
            raise DatabaseViolation(
                "DB-CONNECTION-UNAVAILABLE",
                "the configured PostgreSQL connection is unavailable",
                status="unavailable",
                exit_code=3,
            ) from None

    def _verify_database_identity(
        self, connection: psycopg.Connection[tuple[Any, ...]]
    ) -> None:
        try:
            version_row = connection.execute("SHOW server_version_num").fetchone()
            encoding_row = connection.execute("SHOW server_encoding").fetchone()
            timezone_row = connection.execute("SHOW TimeZone").fetchone()
            locale_row = connection.execute(
                """
                SELECT datlocprovider, datlocale
                FROM pg_catalog.pg_database
                WHERE datname = current_database()
                """
            ).fetchone()
            if (
                version_row is None
                or encoding_row is None
                or timezone_row is None
                or locale_row is None
            ):
                raise ValueError
            version = int(version_row[0])
            encoding = str(encoding_row[0])
            timezone = str(timezone_row[0])
            provider, locale = locale_row
        except psycopg.Error, TypeError, ValueError:
            raise DatabaseViolation(
                "DB-DATABASE-IDENTITY",
                "database identity properties could not be verified",
            ) from None
        expected = self._packaged.manifest
        if version != int(expected["postgresql"]["server_version_num"]):
            raise DatabaseViolation(
                "DB-PG-VERSION", "PostgreSQL must be exactly version 18.4"
            )
        if (
            encoding != expected["database"]["encoding"]
            or timezone != expected["database"]["timezone"]
            or provider != "b"
            or locale != expected["database"]["locale"]
        ):
            raise DatabaseViolation(
                "DB-DATABASE-IDENTITY",
                "database encoding, timezone, or locale is not the frozen identity",
            )

    def _inspect_schema(
        self,
        connection: psycopg.Connection[tuple[Any, ...]],
        *,
        allow_empty: bool,
    ) -> SchemaStatus:
        try:
            objects = connection.execute(
                """
                SELECT relation.relname, relation.relkind
                FROM pg_catalog.pg_class AS relation
                JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'armi'
                  AND relation.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
                ORDER BY relation.relname, relation.relkind
                """
            ).fetchall()
            exists_row = connection.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM pg_catalog.pg_namespace
                    WHERE nspname = 'armi'
                )
                """
            ).fetchone()
            if exists_row is None:
                raise ValueError
            schema_exists = exists_row[0] is True
        except psycopg.Error, ValueError:
            raise DatabaseViolation(
                "DB-SCHEMA-INVARIANT", "the schema catalog could not be inspected"
            ) from None
        if not schema_exists and not objects:
            if allow_empty:
                return SchemaStatus(
                    "empty",
                    len(self._packaged.migrations),
                    0,
                    self.migration_set_sha256,
                    None,
                )
            raise DatabaseViolation(
                "DB-SCHEMA-MISSING", "the required schema baseline is not installed"
            )
        if ("schema_migrations", "r") not in objects:
            raise DatabaseViolation(
                "DB-SCHEMA-DIRTY",
                "the schema contains an incomplete or unmanifested object set",
            )
        self._verify_table_shapes(
            connection,
            ("schema_migrations",),
            applied_version=1,
        )
        applied = self._read_applied(connection)
        target = len(self._packaged.migrations)
        for expected, row in enumerate(applied, start=1):
            if row[0] != expected:
                raise DatabaseViolation(
                    "DB-SCHEMA-GAP", "the applied migration sequence has a gap"
                )
            if expected > target:
                continue
            packaged = self._packaged.migrations[expected - 1]
            if row[1] != packaged[1] or row[2] != packaged[2]:
                raise DatabaseViolation(
                    "DB-SCHEMA-HASH", "an applied migration identity has drifted"
                )
        if applied and applied[-1][0] > target:
            raise DatabaseViolation(
                "DB-SCHEMA-AHEAD", "the database schema is ahead of this Runtime"
            )
        applied_version = len(applied)
        expected_objects = [("schema_migrations", "r")]
        expected_tables = ["schema_migrations"]
        if applied_version >= 3:
            expected_objects.insert(0, ("artifacts", "r"))
            expected_tables.insert(0, "artifacts")
        if applied_version >= 4:
            expected_objects.insert(1, ("audit_events", "r"))
            expected_tables.insert(1, "audit_events")
        if applied_version >= 5:
            expected_objects.insert(2, ("durable_work", "r"))
            expected_objects.insert(3, ("outbox_items", "r"))
            expected_tables.insert(2, "durable_work")
            expected_tables.insert(3, "outbox_items")
        if applied_version >= 6:
            birth_tables = (
                "life_generations",
                "parties",
                "prompt_documents",
                "prompt_revisions",
                "runtime_bundle_activations",
                "subject_component_heads",
                "subject_component_revisions",
                "subjects",
            )
            expected_objects.extend((name, "r") for name in birth_tables)
            expected_tables.extend(birth_tables)
            expected_objects.sort()
            expected_tables.sort()
        if applied_version >= 7:
            expected_objects.append(("runtime_instances", "r"))
            expected_tables.append("runtime_instances")
            expected_objects.sort()
            expected_tables.sort()
        if applied_version >= 8:
            expected_objects.append(("runtime_recovery_runs", "r"))
            expected_tables.append("runtime_recovery_runs")
            expected_objects.sort()
            expected_tables.sort()
        if applied_version >= 9:
            scene_tables = ("interaction_scenes", "scene_timeline_items")
            expected_objects.extend((name, "r") for name in scene_tables)
            expected_tables.extend(scene_tables)
            expected_objects.sort()
            expected_tables.sort()
        if applied_version >= 10:
            input_tables = (
                "creator_input_interactions",
                "external_evidence",
                "opportunities",
            )
            expected_objects.extend((name, "r") for name in input_tables)
            expected_tables.extend(input_tables)
            expected_objects.sort()
            expected_tables.sort()
        if applied_version >= 11:
            context_tables = ("cognitive_episodes", "cognitive_context_items")
            expected_objects.extend((name, "r") for name in context_tables)
            expected_tables.extend(context_tables)
            expected_objects.sort()
            expected_tables.sort()
        if applied_version >= 12:
            expected_objects.append(("cognitive_attempts", "r"))
            expected_tables.append("cognitive_attempts")
            expected_objects.sort()
            expected_tables.sort()
        if applied_version >= 13:
            candidate_tables = (
                "cognitive_candidate_basis_links",
                "cognitive_candidate_validation_items",
                "cognitive_candidate_validations",
            )
            expected_objects.extend((name, "r") for name in candidate_tables)
            expected_tables.extend(candidate_tables)
            expected_objects.sort()
            expected_tables.sort()
        if applied_version >= 14:
            subject_commit_tables = (
                "accepted_experiences",
                "cognitive_candidate_applications",
                "experience_evidence_links",
                "subject_commits",
            )
            expected_objects.extend((name, "r") for name in subject_commit_tables)
            expected_tables.extend(subject_commit_tables)
            expected_objects.sort()
            expected_tables.sort()
        if applied_version >= 15:
            capability_tables = (
                "capabilities",
                "capability_request_basis_links",
                "capability_request_decisions",
                "capability_requests",
                "permission_grants",
            )
            expected_objects.extend((name, "r") for name in capability_tables)
            expected_tables.extend(capability_tables)
            expected_objects.sort()
            expected_tables.sort()
        if applied_version >= 16:
            response_tables = (
                "action_intent_revisions",
                "action_intents",
                "creator_response_operations",
                "formal_no_action_decisions",
            )
            expected_objects.extend((name, "r") for name in response_tables)
            expected_tables.extend(response_tables)
            expected_objects.sort()
            expected_tables.sort()
        if objects != expected_objects:
            raise DatabaseViolation(
                "DB-SCHEMA-DIRTY",
                "the schema contains an incomplete or unmanifested object set",
            )
        self._verify_table_shapes(
            connection,
            tuple(expected_tables),
            applied_version=applied_version,
        )
        if not allow_empty and len(applied) < target:
            raise DatabaseViolation(
                "DB-SCHEMA-MISSING", "the required schema target is not installed"
            )
        if len(applied) == target:
            self._run_invariants(connection)
        catalog = self._catalog_digest(connection)
        return SchemaStatus(
            "current" if len(applied) == target else "behind",
            target,
            len(applied),
            self.migration_set_sha256,
            catalog,
        )

    def _verify_table_shapes(
        self,
        connection: psycopg.Connection[tuple[Any, ...]],
        table_names: tuple[str, ...],
        *,
        applied_version: int,
    ) -> None:
        try:
            columns = connection.execute(
                """
                SELECT
                    relation.relname,
                    attribute.attname,
                    pg_catalog.format_type(attribute.atttypid, attribute.atttypmod),
                    attribute.attnotnull
                FROM pg_catalog.pg_attribute AS attribute
                JOIN pg_catalog.pg_class AS relation
                    ON relation.oid = attribute.attrelid
                JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'armi'
                  AND relation.relname = ANY(%s)
                  AND attribute.attnum > 0
                  AND NOT attribute.attisdropped
                ORDER BY relation.relname, attribute.attnum
                """,
                (list(table_names),),
            ).fetchall()
        except psycopg.Error:
            raise DatabaseViolation(
                "DB-SCHEMA-INVARIANT", "the manifest tables could not be inspected"
            ) from None
        actual_columns: dict[str, list[tuple[str, str, bool]]] = {}
        for table_name, name, type_name, not_null in columns:
            actual_columns.setdefault(str(table_name), []).append(
                (str(name), str(type_name), bool(not_null))
            )
        for table_name in table_names:
            expected = _EXPECTED_TABLE_COLUMNS.get(table_name)
            if table_name == "runtime_recovery_runs" and expected is not None:
                added_columns = max(0, 16 - max(applied_version, 9))
                if added_columns:
                    expected = expected[:-added_columns]
            if table_name == "opportunities" and expected is not None:
                if applied_version < 14:
                    expected = expected[:-4]
                if applied_version < 11:
                    expected = expected[:-1]
            if table_name == "cognitive_episodes" and expected is not None:
                if applied_version < 12:
                    expected = expected[:-5]
                elif applied_version < 13:
                    expected = expected[:-4]
                elif applied_version < 14:
                    expected = expected[:-2]
            if (
                table_name == "subject_component_revisions"
                and applied_version < 14
                and expected is not None
            ):
                expected = tuple(
                    item
                    for item in expected
                    if item[0] not in {"proposal_ref", "semantic_digest"}
                )
            if tuple(actual_columns.get(table_name, ())) != expected:
                raise DatabaseViolation(
                    "DB-SCHEMA-DIRTY",
                    f"a manifest table shape has drifted: {table_name}",
                )
        try:
            constraint_kinds = connection.execute(
                """
                SELECT relation.relname, constraint_value.contype
                FROM pg_catalog.pg_constraint AS constraint_value
                JOIN pg_catalog.pg_class AS relation
                    ON relation.oid = constraint_value.conrelid
                JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'armi'
                  AND relation.relname = ANY(%s)
                ORDER BY relation.relname, constraint_value.contype
                """,
                (list(table_names),),
            ).fetchall()
        except psycopg.Error:
            raise DatabaseViolation(
                "DB-SCHEMA-INVARIANT",
                "the manifest table constraints could not be inspected",
            ) from None
        actual_constraints: dict[str, list[str]] = {}
        for table_name, kind in constraint_kinds:
            actual_constraints.setdefault(str(table_name), []).append(str(kind))
        for table_name in table_names:
            actual = tuple(actual_constraints.get(table_name, ()))
            expected = _EXPECTED_CONSTRAINT_KINDS.get(table_name)
            if table_name == "runtime_recovery_runs" and expected is not None:
                prior_kinds = list(expected)
                added_constraints = max(0, 16 - max(applied_version, 9))
                for _ in range(added_constraints):
                    prior_kinds.remove("c")
                    prior_kinds.remove("n")
                expected = tuple(prior_kinds)
            if table_name == "cognitive_episodes" and expected is not None:
                prior_kinds = list(expected)
                if applied_version < 14:
                    prior_kinds.remove("c")
                if applied_version < 13:
                    prior_kinds.remove("c")
                expected = tuple(prior_kinds)
            if table_name == "opportunities" and expected is not None:
                prior_kinds = list(expected)
                if applied_version < 14:
                    for kind in ("c", "c", "f", "f", "n", "n", "u"):
                        prior_kinds.remove(kind)
                if applied_version < 11:
                    prior_kinds.remove("c")
                    prior_kinds.remove("u")
                expected = tuple(prior_kinds)
            if (
                table_name == "subject_component_revisions"
                and applied_version < 14
                and expected is not None
            ):
                prior_kinds = list(expected)
                prior_kinds.remove("c")
                prior_kinds.remove("f")
                prior_kinds.remove("f")
                expected = tuple(prior_kinds)
            if (
                table_name == "interaction_scenes"
                and applied_version < 10
                and expected is not None
            ):
                prior_kinds = list(expected)
                prior_kinds.remove("u")
                expected = tuple(prior_kinds)
            durable_with_subject = (
                tuple(sorted((*expected, "f")))
                if table_name == "durable_work" and expected is not None
                else None
            )
            if actual != expected and actual != durable_with_subject:
                raise DatabaseViolation(
                    "DB-SCHEMA-DIRTY",
                    f"a manifest table constraint set has drifted: {table_name}",
                )

    def _read_applied(
        self, connection: psycopg.Connection[tuple[Any, ...]]
    ) -> list[tuple[int, str, str]]:
        try:
            rows = connection.execute(
                """
                SELECT version, name, sha256
                FROM armi.schema_migrations
                ORDER BY version
                """
            ).fetchall()
            return [(int(row[0]), str(row[1]), str(row[2])) for row in rows]
        except psycopg.Error, TypeError, ValueError:
            raise DatabaseViolation(
                "DB-SCHEMA-DIRTY", "the migration ledger could not be read"
            ) from None

    def _run_invariants(self, connection: psycopg.Connection[tuple[Any, ...]]) -> None:
        try:
            violations = connection.execute(
                sql.SQL(
                    cast(
                        LiteralString,
                        self._packaged.invariants.decode("utf-8"),
                    )
                )
            ).fetchall()
        except UnicodeDecodeError, psycopg.Error:
            raise DatabaseViolation(
                "DB-SCHEMA-INVARIANT", "the read-only schema invariants failed"
            ) from None
        if violations:
            code = str(violations[0][0])
            if code not in KNOWN_DATABASE_CODES:
                code = "DB-SCHEMA-INVARIANT"
            raise DatabaseViolation(code, "a read-only schema invariant was violated")

    def _catalog_digest(self, connection: psycopg.Connection[tuple[Any, ...]]) -> str:
        try:
            columns = connection.execute(
                """
                SELECT
                    relation.relname,
                    attribute.attname,
                    pg_catalog.format_type(attribute.atttypid, attribute.atttypmod),
                    attribute.attnotnull,
                    COALESCE(
                        pg_catalog.pg_get_expr(default_value.adbin, default_value.adrelid),
                        ''
                    )
                FROM pg_catalog.pg_attribute AS attribute
                JOIN pg_catalog.pg_class AS relation
                    ON relation.oid = attribute.attrelid
                JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.oid = relation.relnamespace
                LEFT JOIN pg_catalog.pg_attrdef AS default_value
                    ON default_value.adrelid = relation.oid
                   AND default_value.adnum = attribute.attnum
                WHERE namespace.nspname = 'armi'
                  AND relation.relkind IN ('r', 'p')
                  AND attribute.attnum > 0
                  AND NOT attribute.attisdropped
                ORDER BY relation.relname, attribute.attnum
                """
            ).fetchall()
            constraints = connection.execute(
                """
                SELECT relation.relname,
                       constraint_value.contype,
                       pg_catalog.pg_get_constraintdef(constraint_value.oid, false)
                FROM pg_catalog.pg_constraint AS constraint_value
                JOIN pg_catalog.pg_class AS relation
                    ON relation.oid = constraint_value.conrelid
                JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'armi'
                  AND relation.relkind IN ('r', 'p')
                ORDER BY relation.relname,
                         constraint_value.contype,
                         pg_catalog.pg_get_constraintdef(constraint_value.oid, false)
                """
            ).fetchall()
            objects = connection.execute(
                """
                SELECT relation.relname, relation.relkind
                FROM pg_catalog.pg_class AS relation
                JOIN pg_catalog.pg_namespace AS namespace
                    ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'armi'
                  AND relation.relkind IN ('r', 'p')
                ORDER BY relation.relname, relation.relkind
                """
            ).fetchall()
        except psycopg.Error:
            raise DatabaseViolation(
                "DB-SCHEMA-INVARIANT", "the schema catalog digest could not be built"
            ) from None
        value = {
            "schema": "armi",
            "objects": [
                {"kind": str(kind), "name": str(name)} for name, kind in objects
            ],
            "columns": [
                {
                    "table": str(table_name),
                    "name": str(name),
                    "type": str(type_name),
                    "not_null": bool(not_null),
                    "default": str(default),
                }
                for table_name, name, type_name, not_null, default in columns
            ],
            "constraints": [
                {
                    "table": str(table_name),
                    "type": str(kind),
                    "definition": str(definition),
                }
                for table_name, kind, definition in constraints
            ],
        }
        return _digest(rfc8785.dumps(cast(Any, value)))


__all__ = ("DatabaseViolation", "PostgreSQLSchemaGateway", "SchemaStatus")
