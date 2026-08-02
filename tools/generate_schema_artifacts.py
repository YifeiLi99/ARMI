"""Generate or verify authoritative schema and database-role governance artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

import rfc8785

_SCHEMA_ROOT = Path("schema")
_MIRROR_ROOT = Path(
    "apps/armi-runtime/src/armi_runtime/composition/runtime_resources/schema"
)
_INVARIANTS = Path("checks/invariants.sql")
_MANIFEST = Path("manifests/schema-manifest.json")
_ROLE_MANIFEST = Path("manifests/database-role-manifest.json")
_MIGRATION_NAME = re.compile(
    r"^(?P<version>[0-9]{4})_(?P<name>[a-z][a-z0-9_]{0,63})\.sql$"
)


def _digest(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _require_text_file(path: Path) -> bytes:
    try:
        value = path.read_bytes()
    except OSError:
        raise ValueError("DB-SCHEMA-MISSING") from None
    if value.startswith(b"\xef\xbb\xbf") or b"\r" in value or not value.endswith(b"\n"):
        raise ValueError("DB-MANIFEST-DRIFT")
    try:
        value.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("DB-MANIFEST-DRIFT") from None
    return value


def build_role_manifest() -> dict[str, object]:
    safe_attributes = {
        "superuser": False,
        "createdb": False,
        "createrole": False,
        "replication": False,
        "bypassrls": False,
    }
    birth_insert_columns = {
        "armi.subjects": [
            "subject_id",
            "singleton_key",
            "birth_request_id",
            "birth_idempotency_key",
            "birth_manifest_digest",
            "current_generation_id",
            "current_bundle_activation_id",
        ],
        "armi.life_generations": [
            "life_generation_id",
            "subject_id",
            "generation_no",
            "status",
            "opened_subject_version",
            "activation_reason",
        ],
        "armi.runtime_bundle_activations": [
            "bundle_activation_id",
            "subject_id",
            "bundle_version",
            "bundle_digest",
            "manifest_artifact_id",
            "schema_baseline_digest",
            "fixed_policy_digest",
            "fixed_prompt_set_digest",
            "creator_asset_digest",
            "status",
            "activated_by_party_id",
        ],
        "armi.parties": [
            "party_id",
            "party_kind",
            "represented_subject_id",
            "creator_role",
        ],
        "armi.prompt_documents": [
            "prompt_document_id",
            "subject_id",
            "prompt_kind",
            "write_authority",
            "current_revision_id",
        ],
        "armi.prompt_revisions": [
            "prompt_revision_id",
            "prompt_document_id",
            "revision_no",
            "content_artifact_id",
            "content_digest",
            "author_party_id",
            "change_reason",
        ],
        "armi.subject_component_heads": [
            "subject_id",
            "component_kind",
            "current_revision_id",
            "component_version",
        ],
        "armi.subject_component_revisions": [
            "component_revision_id",
            "subject_id",
            "component_kind",
            "component_version",
            "previous_revision_id",
            "origin_kind",
            "origin_ref",
            "subject_commit_id",
            "proposal_ref",
            "semantic_digest",
            "semantic_payload",
            "privacy_scope",
        ],
        "armi.interaction_scenes": [
            "scene_id",
            "subject_id",
            "scene_key",
            "scene_kind",
            "primary_party_id",
            "audience_scope",
            "current_status",
            "schema_version",
        ],
    }
    birth_objects = [
        {
            "kind": "table",
            "name": name,
            "owner": "armi_owner",
            "public_privileges": [],
            "grants": {
                "armi_runtime": ["SELECT"],
                "armi_admin": [],
                "armi_migrator": [],
            },
            "column_grants": {
                "armi_runtime": {"INSERT": columns},
                "armi_admin": {},
                "armi_migrator": {},
            },
        }
        for name, columns in birth_insert_columns.items()
    ]
    for item in birth_objects:
        name = item["name"]
        runtime_columns = item["column_grants"]["armi_runtime"]
        if name == "armi.subjects":
            runtime_columns["UPDATE"] = ["subject_version"]
        elif name == "armi.subject_component_heads":
            runtime_columns["UPDATE"] = ["current_revision_id", "component_version"]
    authority_object = {
        "kind": "table",
        "name": "armi.runtime_instances",
        "owner": "armi_owner",
        "public_privileges": [],
        "grants": {
            "armi_runtime": ["SELECT"],
            "armi_admin": [],
            "armi_migrator": [],
        },
        "column_grants": {
            "armi_runtime": {
                "INSERT": [
                    "runtime_instance_id",
                    "subject_id",
                    "life_generation_id",
                    "bundle_activation_id",
                    "fence_token",
                    "status",
                    "lease_expires_at",
                    "schema_version",
                ],
                "UPDATE": [
                    "status",
                    "last_heartbeat_at",
                    "lease_expires_at",
                    "stopped_at",
                ],
            },
            "armi_admin": {},
            "armi_migrator": {},
        },
    }
    recovery_object = {
        "kind": "table",
        "name": "armi.runtime_recovery_runs",
        "owner": "armi_owner",
        "public_privileges": [],
        "grants": {
            "armi_runtime": ["SELECT"],
            "armi_admin": [],
            "armi_migrator": [],
        },
        "column_grants": {
            "armi_runtime": {
                "INSERT": [
                    "recovery_run_id",
                    "runtime_instance_id",
                    "subject_id",
                    "life_generation_id",
                    "bundle_activation_id",
                    "fence_token",
                    "status",
                    "requeued_work_count",
                    "terminal_work_count",
                    "requeued_outbox_count",
                    "dead_outbox_count",
                    "resumable_work_count",
                    "resumable_outbox_count",
                    "resumable_opportunity_count",
                    "resumable_cognitive_episode_count",
                    "resumable_model_attempt_count",
                    "resumable_candidate_validation_count",
                    "resumable_subject_commit_count",
                    "resumable_capability_request_count",
                    "resumable_response_operation_count",
                    "resumable_effect_count",
                    "resumable_effect_outbox_count",
                    "resumable_effect_attempt_count",
                    "reliable_effect_observation_count",
                    "creator_response_delivery_count",
                    "resumable_web_observation_count",
                    "unknown_web_observation_attempt_count",
                    "critical_artifact_count",
                    "blocker_count",
                    "schema_version",
                ],
                "UPDATE": [
                    "status",
                    "completed_at",
                    "requeued_work_count",
                    "terminal_work_count",
                    "requeued_outbox_count",
                    "dead_outbox_count",
                    "resumable_work_count",
                    "resumable_outbox_count",
                    "resumable_opportunity_count",
                    "resumable_cognitive_episode_count",
                    "resumable_model_attempt_count",
                    "resumable_candidate_validation_count",
                    "resumable_subject_commit_count",
                    "resumable_capability_request_count",
                    "resumable_response_operation_count",
                    "resumable_effect_count",
                    "resumable_effect_outbox_count",
                    "resumable_effect_attempt_count",
                    "reliable_effect_observation_count",
                    "creator_response_delivery_count",
                    "resumable_web_observation_count",
                    "unknown_web_observation_attempt_count",
                    "critical_artifact_count",
                    "blocker_count",
                    "summary_digest",
                ],
            },
            "armi_admin": {},
            "armi_migrator": {},
        },
    }
    timeline_object = {
        "kind": "table",
        "name": "armi.scene_timeline_items",
        "owner": "armi_owner",
        "public_privileges": [],
        "grants": {
            "armi_runtime": ["SELECT"],
            "armi_admin": [],
            "armi_migrator": [],
        },
        "column_grants": {
            "armi_runtime": {
                "INSERT": [
                    "timeline_item_id",
                    "scene_id",
                    "source_kind",
                    "source_ref",
                    "source_event_no",
                    "result_status",
                    "occurred_at",
                    "schema_version",
                ]
            },
            "armi_admin": {},
            "armi_migrator": {},
        },
    }
    creator_input_objects = [
        {
            "kind": "table",
            "name": "armi.creator_input_interactions",
            "owner": "armi_owner",
            "public_privileges": [],
            "grants": {
                "armi_runtime": ["SELECT"],
                "armi_admin": [],
                "armi_migrator": [],
            },
            "column_grants": {
                "armi_runtime": {
                    "INSERT": [
                        "creator_interaction_id",
                        "subject_id",
                        "scene_id",
                        "creator_party_id",
                        "purpose",
                        "idempotency_key",
                        "request_digest",
                        "content_digest",
                        "trace_id",
                        "schema_version",
                    ]
                },
                "armi_admin": {},
                "armi_migrator": {},
            },
        },
        {
            "kind": "table",
            "name": "armi.external_evidence",
            "owner": "armi_owner",
            "public_privileges": [],
            "grants": {
                "armi_runtime": ["SELECT"],
                "armi_admin": [],
                "armi_migrator": [],
            },
            "column_grants": {
                "armi_runtime": {
                    "INSERT": [
                        "evidence_id",
                        "creator_interaction_id",
                        "subject_id",
                        "scene_id",
                        "creator_party_id",
                        "artifact_id",
                        "source_kind",
                        "trust_status",
                        "privacy_scope",
                        "acceptance_status",
                        "schema_version",
                    ]
                },
                "armi_admin": {},
                "armi_migrator": {},
            },
        },
        {
            "kind": "table",
            "name": "armi.opportunities",
            "owner": "armi_owner",
            "public_privileges": [],
            "grants": {
                "armi_runtime": ["SELECT"],
                "armi_admin": [],
                "armi_migrator": [],
            },
            "column_grants": {
                "armi_runtime": {
                    "INSERT": [
                        "opportunity_id",
                        "evidence_id",
                        "subject_id",
                        "scene_id",
                        "creator_party_id",
                        "purpose",
                        "eligibility_status",
                        "current_disposition",
                        "root_opportunity_id",
                        "predecessor_opportunity_id",
                        "reconsideration_no",
                        "schema_version",
                    ],
                    "UPDATE": ["current_disposition", "selected_at", "resolved_at"],
                },
                "armi_admin": {},
                "armi_migrator": {},
            },
        },
    ]
    context_objects = [
        {
            "kind": "table",
            "name": "armi.cognitive_episodes",
            "owner": "armi_owner",
            "public_privileges": [],
            "grants": {
                "armi_runtime": ["SELECT"],
                "armi_admin": [],
                "armi_migrator": [],
            },
            "column_grants": {
                "armi_runtime": {
                    "INSERT": [
                        "cognitive_episode_id",
                        "opportunity_id",
                        "subject_id",
                        "scene_id",
                        "creator_party_id",
                        "purpose",
                        "status",
                        "base_subject_version",
                        "base_state_epoch",
                        "bundle_activation_id",
                        "policy_digest",
                        "mechanism_identity",
                        "mechanism_config_digest",
                        "trace_id",
                        "schema_version",
                    ],
                    "UPDATE": [
                        "status",
                        "context_manifest_artifact_id",
                        "compiled_context_artifact_id",
                        "context_digest",
                        "failure_code",
                        "prepared_at",
                        "model_returned_at",
                        "final_disposition",
                        "validated_at",
                        "application_resolution",
                        "committed_at",
                    ],
                },
                "armi_admin": {},
                "armi_migrator": {},
            },
        },
        {
            "kind": "table",
            "name": "armi.cognitive_context_items",
            "owner": "armi_owner",
            "public_privileges": [],
            "grants": {
                "armi_runtime": ["SELECT"],
                "armi_admin": [],
                "armi_migrator": [],
            },
            "column_grants": {
                "armi_runtime": {
                    "INSERT": [
                        "context_item_id",
                        "cognitive_episode_id",
                        "ordinal",
                        "section",
                        "item_kind",
                        "source_kind",
                        "source_ref",
                        "source_version",
                        "source_digest",
                        "trust_class",
                        "privacy_scope",
                        "disposition",
                        "reason_code",
                        "content_bytes",
                        "schema_version",
                    ]
                },
                "armi_admin": {},
                "armi_migrator": {},
            },
        },
    ]
    model_attempt_object = {
        "kind": "table",
        "name": "armi.cognitive_attempts",
        "owner": "armi_owner",
        "public_privileges": [],
        "grants": {
            "armi_runtime": ["SELECT"],
            "armi_admin": [],
            "armi_migrator": [],
        },
        "column_grants": {
            "armi_runtime": {
                "INSERT": [
                    "model_attempt_id",
                    "cognitive_episode_id",
                    "work_id",
                    "work_attempt_id",
                    "attempt_no",
                    "binding_digest",
                    "provider",
                    "model_id",
                    "version_policy",
                    "profile",
                    "request_schema_version",
                    "candidate_schema_version",
                    "pricing_snapshot_id",
                    "credential_identity",
                    "request_artifact_id",
                    "request_digest",
                    "dispatch_status",
                    "schema_version",
                ],
                "UPDATE": [
                    "dispatch_status",
                    "provider_request_id",
                    "provider_model_id",
                    "response_artifact_id",
                    "input_tokens",
                    "output_tokens",
                    "cached_input_tokens",
                    "estimated_cost_microyuan",
                    "result_status",
                    "error_code",
                    "dispatched_at",
                    "settled_at",
                ],
            },
            "armi_admin": {},
            "armi_migrator": {},
        },
    }
    candidate_validation_objects = [
        {
            "kind": "table",
            "name": "armi.cognitive_candidate_validations",
            "owner": "armi_owner",
            "public_privileges": [],
            "grants": {
                "armi_runtime": ["SELECT", "INSERT"],
                "armi_admin": [],
                "armi_migrator": [],
            },
        },
        {
            "kind": "table",
            "name": "armi.cognitive_candidate_validation_items",
            "owner": "armi_owner",
            "public_privileges": [],
            "grants": {
                "armi_runtime": ["SELECT", "INSERT"],
                "armi_admin": [],
                "armi_migrator": [],
            },
        },
        {
            "kind": "table",
            "name": "armi.cognitive_candidate_basis_links",
            "owner": "armi_owner",
            "public_privileges": [],
            "grants": {
                "armi_runtime": ["SELECT", "INSERT"],
                "armi_admin": [],
                "armi_migrator": [],
            },
        },
    ]
    subject_commit_objects = [
        {
            "kind": "table",
            "name": name,
            "owner": "armi_owner",
            "public_privileges": [],
            "grants": {
                "armi_runtime": ["SELECT", "INSERT"],
                "armi_admin": [],
                "armi_migrator": [],
            },
        }
        for name in (
            "armi.subject_commits",
            "armi.accepted_experiences",
            "armi.experience_evidence_links",
            "armi.cognitive_candidate_applications",
        )
    ]
    capability_objects = [
        {
            "kind": "table",
            "name": "armi.capabilities",
            "owner": "armi_owner",
            "public_privileges": [],
            "grants": {
                "armi_runtime": ["SELECT"],
                "armi_admin": [],
                "armi_migrator": [],
            },
        },
        {
            "kind": "table",
            "name": "armi.capability_request_basis_links",
            "owner": "armi_owner",
            "public_privileges": [],
            "grants": {
                "armi_runtime": ["SELECT"],
                "armi_admin": [],
                "armi_migrator": [],
            },
            "column_grants": {
                "armi_runtime": {
                    "INSERT": [
                        "capability_request_id",
                        "context_item_id",
                        "ordinal",
                    ],
                },
                "armi_admin": {},
                "armi_migrator": {},
            },
        },
        {
            "kind": "table",
            "name": "armi.capability_request_decisions",
            "owner": "armi_owner",
            "public_privileges": [],
            "grants": {
                "armi_runtime": ["SELECT"],
                "armi_admin": [],
                "armi_migrator": [],
            },
            "column_grants": {
                "armi_runtime": {
                    "INSERT": [
                        "capability_decision_id",
                        "capability_request_id",
                        "creator_party_id",
                        "expected_request_version",
                        "resulting_request_version",
                        "decision_kind",
                        "command_digest",
                        "scope_digest",
                        "reason_code",
                        "schema_version",
                    ],
                },
                "armi_admin": {},
                "armi_migrator": {},
            },
        },
        {
            "kind": "table",
            "name": "armi.capability_requests",
            "owner": "armi_owner",
            "public_privileges": [],
            "grants": {
                "armi_runtime": ["SELECT"],
                "armi_admin": [],
                "armi_migrator": [],
            },
            "column_grants": {
                "armi_runtime": {
                    "INSERT": [
                        "capability_request_id",
                        "subject_commit_id",
                        "proposal_ref",
                        "subject_id",
                        "interaction_scene_id",
                        "creator_party_id",
                        "capability_id",
                        "capability_kind",
                        "operation_class",
                        "audience_scope",
                        "data_scope",
                        "purpose",
                        "workspace_scope",
                        "artifact_scope",
                        "network_access",
                        "requested_valid_for_seconds",
                        "requested_max_uses",
                        "requested_max_payload_bytes",
                        "request_digest",
                        "schema_version",
                    ],
                    "UPDATE": [
                        "current_status",
                        "request_version",
                        "resolved_by_party_id",
                        "resolution_reason_class",
                        "resolved_at",
                    ],
                },
                "armi_admin": {},
                "armi_migrator": {},
            },
        },
        {
            "kind": "table",
            "name": "armi.permission_grants",
            "owner": "armi_owner",
            "public_privileges": [],
            "grants": {
                "armi_runtime": ["SELECT"],
                "armi_admin": [],
                "armi_migrator": [],
            },
            "column_grants": {
                "armi_runtime": {
                    "INSERT": [
                        "grant_id",
                        "capability_request_id",
                        "creator_party_id",
                        "capability_id",
                        "subject_id",
                        "interaction_scene_id",
                        "operation_class",
                        "audience_scope",
                        "data_scope",
                        "purpose",
                        "valid_from",
                        "valid_until",
                        "max_uses",
                        "max_payload_bytes",
                        "scope_digest",
                        "schema_version",
                    ],
                    "UPDATE": ["consumed_uses", "status", "revoked_at"],
                },
                "armi_admin": {},
                "armi_migrator": {},
            },
        },
    ]
    response_objects = [
        {
            "kind": "table",
            "name": "armi.action_intents",
            "owner": "armi_owner",
            "public_privileges": [],
            "grants": {
                "armi_runtime": ["SELECT"],
                "armi_admin": [],
                "armi_migrator": [],
            },
            "column_grants": {
                "armi_runtime": {
                    "INSERT": [
                        "action_intent_id",
                        "subject_id",
                        "interaction_scene_id",
                        "creator_party_id",
                        "root_opportunity_id",
                        "purpose",
                        "current_revision_id",
                        "schema_version",
                    ],
                    "UPDATE": ["current_revision_id"],
                },
                "armi_admin": {},
                "armi_migrator": {},
            },
        },
        {
            "kind": "table",
            "name": "armi.action_intent_revisions",
            "owner": "armi_owner",
            "public_privileges": [],
            "grants": {
                "armi_runtime": ["SELECT"],
                "armi_admin": [],
                "armi_migrator": [],
            },
            "column_grants": {
                "armi_runtime": {
                    "INSERT": [
                        "action_intent_revision_id",
                        "action_intent_id",
                        "revision_no",
                        "response_artifact_id",
                        "response_digest",
                        "response_bytes",
                        "media_type",
                        "capability_kind",
                        "operation_class",
                        "audience_scope",
                        "data_scope",
                        "purpose",
                        "candidate_validation_id",
                        "proposal_ref",
                        "subject_commit_id",
                        "schema_version",
                    ]
                },
                "armi_admin": {},
                "armi_migrator": {},
            },
        },
        {
            "kind": "table",
            "name": "armi.formal_no_action_decisions",
            "owner": "armi_owner",
            "public_privileges": [],
            "grants": {
                "armi_runtime": ["SELECT"],
                "armi_admin": [],
                "armi_migrator": [],
            },
            "column_grants": {
                "armi_runtime": {
                    "INSERT": [
                        "formal_no_action_id",
                        "candidate_application_id",
                        "candidate_validation_id",
                        "proposal_ref",
                        "root_opportunity_id",
                        "decision_kind",
                        "reason_class",
                        "basis_digest",
                        "schema_version",
                    ]
                },
                "armi_admin": {},
                "armi_migrator": {},
            },
        },
        {
            "kind": "table",
            "name": "armi.creator_response_operations",
            "owner": "armi_owner",
            "public_privileges": [],
            "grants": {
                "armi_runtime": ["SELECT"],
                "armi_admin": [],
                "armi_migrator": [],
            },
            "column_grants": {
                "armi_runtime": {
                    "INSERT": [
                        "creator_response_operation_id",
                        "root_opportunity_id",
                        "subject_id",
                        "interaction_scene_id",
                        "creator_party_id",
                        "action_intent_id",
                        "formal_no_action_id",
                        "admission_work_id",
                        "registration_work_id",
                        "current_status",
                        "matched_grant_id",
                        "completion_digest",
                        "reason_code",
                        "completed_at",
                        "current_policy_decision_id",
                        "effect_id",
                        "effect_registration_digest",
                        "effect_registered_at",
                        "schema_version",
                    ],
                    "UPDATE": [
                        "current_status",
                        "matched_grant_id",
                        "completion_digest",
                        "reason_code",
                        "completed_at",
                        "registration_work_id",
                        "current_policy_decision_id",
                        "effect_id",
                        "effect_registration_digest",
                        "effect_registered_at",
                    ],
                },
                "armi_admin": {},
                "armi_migrator": {},
            },
        },
        {
            "kind": "table",
            "name": "armi.policy_decisions",
            "owner": "armi_owner",
            "public_privileges": [],
            "grants": {
                "armi_runtime": ["SELECT", "INSERT"],
                "armi_admin": [],
                "armi_migrator": [],
            },
            "column_grants": {
                "armi_runtime": {"UPDATE": ["is_current"]},
                "armi_admin": {},
                "armi_migrator": {},
            },
        },
        {
            "kind": "table",
            "name": "armi.effects",
            "owner": "armi_owner",
            "public_privileges": [],
            "grants": {
                "armi_runtime": ["SELECT", "INSERT"],
                "armi_admin": [],
                "armi_migrator": [],
            },
            "column_grants": {
                "armi_runtime": {
                    "UPDATE": [
                        "status",
                        "cancelled_at",
                        "verification_status",
                        "current_attempt_id",
                        "current_observation_id",
                        "settlement_digest",
                        "settled_at",
                    ]
                },
                "armi_admin": {},
                "armi_migrator": {},
            },
        },
        {
            "kind": "table",
            "name": "armi.effect_outbox_items",
            "owner": "armi_owner",
            "public_privileges": [],
            "grants": {
                "armi_runtime": ["SELECT", "INSERT"],
                "armi_admin": [],
                "armi_migrator": [],
            },
            "column_grants": {
                "armi_runtime": {
                    "UPDATE": [
                        "status",
                        "cancelled_at",
                        "available_at",
                        "claim_owner",
                        "claim_expires_at",
                        "claim_token",
                        "attempt_count",
                        "delivered_at",
                        "last_error_code",
                    ]
                },
                "armi_admin": {},
                "armi_migrator": {},
            },
        },
        {
            "kind": "table",
            "name": "armi.creator_response_deliveries",
            "owner": "armi_owner",
            "public_privileges": [],
            "grants": {
                "armi_runtime": ["SELECT"],
                "armi_admin": [],
                "armi_migrator": [],
            },
            "column_grants": {
                "armi_runtime": {
                    "INSERT": [
                        "creator_response_delivery_id",
                        "effect_id",
                        "interaction_scene_id",
                        "creator_party_id",
                        "payload_artifact_id",
                        "payload_digest",
                        "payload_bytes",
                        "receipt_digest",
                        "schema_version",
                    ]
                },
                "armi_admin": {},
                "armi_migrator": {},
            },
        },
        {
            "kind": "table",
            "name": "armi.effect_attempts",
            "owner": "armi_owner",
            "public_privileges": [],
            "grants": {
                "armi_runtime": ["SELECT"],
                "armi_admin": [],
                "armi_migrator": [],
            },
            "column_grants": {
                "armi_runtime": {
                    "INSERT": [
                        "effect_attempt_id",
                        "effect_id",
                        "attempt_no",
                        "adapter_binding",
                        "request_digest",
                        "claim_token",
                        "dispatch_state",
                        "schema_version",
                    ],
                    "UPDATE": [
                        "dispatch_state",
                        "result_status",
                        "error_code",
                        "dispatched_at",
                        "settled_at",
                    ],
                },
                "armi_admin": {},
                "armi_migrator": {},
            },
        },
        {
            "kind": "table",
            "name": "armi.effect_observations",
            "owner": "armi_owner",
            "public_privileges": [],
            "grants": {
                "armi_runtime": ["SELECT"],
                "armi_admin": [],
                "armi_migrator": [],
            },
            "column_grants": {
                "armi_runtime": {
                    "INSERT": [
                        "effect_observation_id",
                        "effect_id",
                        "effect_attempt_id",
                        "observation_kind",
                        "reliability",
                        "receiver_ref",
                        "observation_digest",
                        "schema_version",
                    ]
                },
                "armi_admin": {},
                "armi_migrator": {},
            },
        },
    ]
    web_observation_objects = [
        {
            "kind": "table",
            "name": "armi.web_observation_requests",
            "owner": "armi_owner",
            "public_privileges": [],
            "grants": {
                "armi_runtime": ["SELECT"],
                "armi_admin": [],
                "armi_migrator": [],
            },
            "column_grants": {
                "armi_runtime": {
                    "INSERT": [
                        "web_observation_request_id",
                        "subject_id",
                        "runtime_instance_id",
                        "fence_token",
                        "idempotency_key",
                        "purpose",
                        "operation_class",
                        "request_artifact_id",
                        "request_digest",
                        "binding_id",
                        "work_id",
                        "deadline_at",
                        "max_attempts",
                        "max_cost_microyuan",
                        "status",
                        "schema_version",
                    ],
                    "UPDATE": [
                        "status",
                        "result_artifact_id",
                        "result_digest",
                        "last_error_code",
                        "completed_at",
                    ],
                },
                "armi_admin": {},
                "armi_migrator": {},
            },
        },
        {
            "kind": "table",
            "name": "armi.observation_attempts",
            "owner": "armi_owner",
            "public_privileges": [],
            "grants": {
                "armi_runtime": ["SELECT"],
                "armi_admin": [],
                "armi_migrator": [],
            },
            "column_grants": {
                "armi_runtime": {
                    "INSERT": [
                        "observation_attempt_id",
                        "web_observation_request_id",
                        "work_id",
                        "work_attempt_id",
                        "work_lease_token",
                        "attempt_no",
                        "binding_id",
                        "credential_identity",
                        "dispatch_state",
                        "schema_version",
                    ],
                    "UPDATE": [
                        "dispatch_state",
                        "provider_request_digest",
                        "provider_model_id",
                        "result_artifact_id",
                        "result_digest",
                        "input_tokens",
                        "output_tokens",
                        "web_search_calls",
                        "citation_count",
                        "estimated_cost_microyuan",
                        "result_status",
                        "error_code",
                        "dispatched_at",
                        "settled_at",
                    ],
                },
                "armi_admin": {},
                "armi_migrator": {},
            },
        },
        {
            "kind": "table",
            "name": "armi.observation_tool_calls",
            "owner": "armi_owner",
            "public_privileges": [],
            "grants": {
                "armi_runtime": ["SELECT"],
                "armi_admin": [],
                "armi_migrator": [],
            },
            "column_grants": {
                "armi_runtime": {
                    "INSERT": [
                        "observation_tool_call_id",
                        "observation_attempt_id",
                        "call_no",
                        "action_type",
                        "provider_identity_digest",
                        "action_digest",
                        "completion_status",
                        "schema_version",
                    ]
                },
                "armi_admin": {},
                "armi_migrator": {},
            },
        },
    ]
    return {
        "schema_version": "armi.database-roles.v1",
        "postgresql_version": "18.4",
        "environment_id": {
            "format": "lowercase canonical UUIDv7",
            "physical_role_template": "armi_{environment_uuid_hex}_{role_class}",
            "role_classes": ["runtime", "admin", "migrator"],
        },
        "capability_roles": [
            {
                "name": name,
                "login": False,
                "inherit": False,
                **safe_attributes,
            }
            for name in (
                "armi_owner",
                "armi_migrator",
                "armi_runtime",
                "armi_admin",
            )
        ],
        "login_roles": [
            {
                "class": role_class,
                "login": True,
                "inherit": True,
                **safe_attributes,
            }
            for role_class in ("runtime", "admin", "migrator")
        ],
        "memberships": [
            {
                "member_class": "runtime",
                "role": "armi_runtime",
                "inherit": True,
                "set": False,
                "admin": False,
            },
            {
                "member_class": "admin",
                "role": "armi_admin",
                "inherit": True,
                "set": False,
                "admin": False,
            },
            {
                "member_class": "migrator",
                "role": "armi_migrator",
                "inherit": True,
                "set": False,
                "admin": False,
            },
            {
                "member_class": "migrator",
                "role": "armi_owner",
                "inherit": False,
                "set": True,
                "admin": False,
            },
        ],
        "database_privileges": {
            "public": [],
            "owner": ["CREATE"],
            "runtime": ["CONNECT"],
            "admin": ["CONNECT"],
            "migrator": ["CONNECT"],
            "temporary_allowed": False,
            "create_allowed": False,
        },
        "session": {
            "search_path": ["pg_catalog", "armi"],
            "checkout_requires_session_user": True,
            "checkout_requires_current_user_reset": True,
        },
        "objects": [
            {
                "kind": "schema",
                "name": "armi",
                "owner": "armi_owner",
                "public_privileges": [],
                "grants": {
                    "armi_runtime": ["USAGE"],
                    "armi_admin": ["USAGE"],
                    "armi_migrator": ["USAGE"],
                },
            },
            {
                "kind": "table",
                "name": "armi.schema_migrations",
                "owner": "armi_owner",
                "public_privileges": [],
                "grants": {
                    "armi_runtime": ["SELECT"],
                    "armi_admin": ["SELECT"],
                    "armi_migrator": ["SELECT"],
                },
            },
            {
                "kind": "table",
                "name": "armi.artifacts",
                "owner": "armi_owner",
                "public_privileges": [],
                "grants": {
                    "armi_runtime": ["SELECT"],
                    "armi_admin": [],
                    "armi_migrator": [],
                },
                "column_grants": {
                    "armi_runtime": {
                        "INSERT": [
                            "artifact_id",
                            "content_digest",
                            "media_type",
                            "byte_size",
                            "storage_locator",
                            "logical_kind",
                            "producer_kind",
                            "producer_trace_id",
                            "privacy_scope",
                            "schema_version",
                        ],
                        "UPDATE": ["integrity_status"],
                    },
                    "armi_admin": {},
                    "armi_migrator": {},
                },
            },
            {
                "kind": "table",
                "name": "armi.audit_events",
                "owner": "armi_owner",
                "public_privileges": [],
                "grants": {
                    "armi_runtime": ["SELECT"],
                    "armi_admin": [],
                    "armi_migrator": [],
                },
                "column_grants": {
                    "armi_runtime": {
                        "INSERT": [
                            "audit_event_id",
                            "actor_kind",
                            "actor_ref",
                            "purpose",
                            "operation",
                            "target_kind",
                            "target_ref",
                            "result_status",
                            "trace_id",
                            "sensitivity",
                            "subject_id",
                            "request_kind",
                            "request_ref",
                            "before_version",
                            "after_version",
                            "request_digest",
                            "response_digest",
                            "artifact_digest",
                            "details_digest",
                            "policy_ref",
                            "grant_ref",
                            "bundle_digest",
                            "error_category",
                            "schema_version",
                        ]
                    },
                    "armi_admin": {},
                    "armi_migrator": {},
                },
            },
            {
                "kind": "table",
                "name": "armi.durable_work",
                "owner": "armi_owner",
                "public_privileges": [],
                "grants": {
                    "armi_runtime": ["SELECT"],
                    "armi_admin": [],
                    "armi_migrator": [],
                },
                "column_grants": {
                    "armi_runtime": {
                        "INSERT": [
                            "work_id",
                            "work_kind",
                            "owner_kind",
                            "owner_ref",
                            "subject_id",
                            "idempotency_key",
                            "payload_kind",
                            "payload_ref",
                            "payload_digest",
                            "priority",
                            "not_before",
                            "deadline_at",
                            "status",
                            "max_attempts",
                            "attempt_count",
                            "lease_token",
                            "trace_id",
                            "schema_version",
                        ],
                        "UPDATE": [
                            "status",
                            "not_before",
                            "attempt_count",
                            "current_attempt_id",
                            "lease_owner",
                            "lease_expires_at",
                            "lease_token",
                            "result_kind",
                            "result_ref",
                            "last_error_code",
                            "updated_at",
                        ],
                    },
                    "armi_admin": {},
                    "armi_migrator": {},
                },
            },
            {
                "kind": "table",
                "name": "armi.outbox_items",
                "owner": "armi_owner",
                "public_privileges": [],
                "grants": {
                    "armi_runtime": ["SELECT"],
                    "armi_admin": [],
                    "armi_migrator": [],
                },
                "column_grants": {
                    "armi_runtime": {
                        "INSERT": [
                            "outbox_item_id",
                            "work_id",
                            "message_kind",
                            "payload_digest",
                            "status",
                            "available_at",
                            "claim_token",
                            "attempt_count",
                            "max_attempts",
                            "trace_id",
                            "schema_version",
                        ],
                        "UPDATE": [
                            "status",
                            "available_at",
                            "claimed_by",
                            "claim_expires_at",
                            "claim_token",
                            "attempt_count",
                            "last_error_code",
                            "delivered_at",
                            "updated_at",
                        ],
                    },
                    "armi_admin": {},
                    "armi_migrator": {},
                },
            },
            *birth_objects,
            authority_object,
            recovery_object,
            timeline_object,
            *creator_input_objects,
            *context_objects,
            model_attempt_object,
            *candidate_validation_objects,
            *subject_commit_objects,
            *capability_objects,
            *response_objects,
            *web_observation_objects,
        ],
        "default_privileges": [],
        "security_definer": {
            "entries": [],
            "not_applicable_reason": (
                "M0-S033 has no business or administration function requiring "
                "privilege elevation."
            ),
            "required_search_path": ["pg_catalog", "armi", "pg_temp"],
            "public_execute": False,
        },
        "credential_acl": {
            "policy": "tools/windows-credential-acl-policy.json",
            "activation_step": "M0-S035",
            "active": False,
        },
    }


def build_manifest(schema_root: Path, role_manifest_bytes: bytes) -> dict[str, object]:
    migration_paths = sorted((schema_root / "migrations").glob("*.sql"))
    if not migration_paths:
        raise ValueError("DB-SCHEMA-MISSING")
    migrations: list[dict[str, object]] = []
    migration_set_input = bytearray()
    for expected_version, migration_path in enumerate(migration_paths, start=1):
        relative = migration_path.relative_to(schema_root)
        match = _MIGRATION_NAME.fullmatch(migration_path.name)
        if match is None or int(match.group("version")) != expected_version:
            raise ValueError("DB-SCHEMA-GAP")
        migration = _require_text_file(migration_path)
        migration_digest = _digest(migration)
        path = f"schema/{relative.as_posix()}"
        migrations.append(
            {
                "version": expected_version,
                "name": match.group("name"),
                "path": path,
                "sha256": migration_digest,
            }
        )
        migration_set_input.extend(
            f"{expected_version}\t{path}\t{migration_digest}\n".encode()
        )
    invariant_path = schema_root / _INVARIANTS
    invariants = _require_text_file(invariant_path)
    return {
        "schema_version": "armi.schema-manifest.v1",
        "postgresql": {
            "product": "PostgreSQL",
            "version": "18.4",
            "server_version_num": 180004,
        },
        "database": {
            "encoding": "UTF8",
            "timezone": "UTC",
            "locale_provider": "builtin",
            "locale": "C.UTF-8",
        },
        "target": {"schema": "armi", "version": len(migrations)},
        "migrations": migrations,
        "migration_set_sha256": _digest(bytes(migration_set_input)),
        "invariants": {
            "path": f"schema/{_INVARIANTS.as_posix()}",
            "sha256": _digest(invariants),
            "read_only": True,
        },
        "allowed_objects": [
            {
                "kind": "table",
                "name": "armi.schema_migrations",
                "logical_owner": "schema-governance",
                "activation_step": "M0-S009",
            },
            {
                "kind": "table",
                "name": "armi.artifacts",
                "logical_owner": "artifact-catalog",
                "activation_step": "M0-S012",
            },
            {
                "kind": "table",
                "name": "armi.audit_events",
                "logical_owner": "normal-audit",
                "activation_step": "M0-S013",
            },
            {
                "kind": "table",
                "name": "armi.durable_work",
                "logical_owner": "durable-work",
                "activation_step": "M0-S014",
            },
            {
                "kind": "table",
                "name": "armi.outbox_items",
                "logical_owner": "durable-work",
                "activation_step": "M0-S014",
            },
            {
                "kind": "table",
                "name": "armi.subjects",
                "logical_owner": "subject-continuity",
                "activation_step": "M0-S015",
            },
            {
                "kind": "table",
                "name": "armi.life_generations",
                "logical_owner": "subject-continuity",
                "activation_step": "M0-S015",
            },
            {
                "kind": "table",
                "name": "armi.runtime_bundle_activations",
                "logical_owner": "subject-continuity",
                "activation_step": "M0-S015",
            },
            {
                "kind": "table",
                "name": "armi.parties",
                "logical_owner": "subject-identity",
                "activation_step": "M0-S015",
            },
            {
                "kind": "table",
                "name": "armi.prompt_documents",
                "logical_owner": "prompt-authority",
                "activation_step": "M0-S015",
            },
            {
                "kind": "table",
                "name": "armi.prompt_revisions",
                "logical_owner": "prompt-authority",
                "activation_step": "M0-S015",
            },
            {
                "kind": "table",
                "name": "armi.subject_component_heads",
                "logical_owner": "subject-components",
                "activation_step": "M0-S015",
            },
            {
                "kind": "table",
                "name": "armi.subject_component_revisions",
                "logical_owner": "subject-components",
                "activation_step": "M0-S015",
            },
            {
                "kind": "table",
                "name": "armi.runtime_instances",
                "logical_owner": "runtime-authority",
                "activation_step": "M0-S016",
            },
            {
                "kind": "table",
                "name": "armi.runtime_recovery_runs",
                "logical_owner": "runtime-recovery",
                "activation_step": "M0-S017",
            },
            {
                "kind": "table",
                "name": "armi.interaction_scenes",
                "logical_owner": "scene-authority",
                "activation_step": "M0-S019",
            },
            {
                "kind": "table",
                "name": "armi.scene_timeline_items",
                "logical_owner": "creator-projection",
                "activation_step": "M0-S019",
            },
            {
                "kind": "table",
                "name": "armi.creator_input_interactions",
                "logical_owner": "creator-input-intake",
                "activation_step": "M0-S021",
            },
            {
                "kind": "table",
                "name": "armi.external_evidence",
                "logical_owner": "external-evidence",
                "activation_step": "M0-S021",
            },
            {
                "kind": "table",
                "name": "armi.opportunities",
                "logical_owner": "opportunity-custody",
                "activation_step": "M0-S021",
            },
            {
                "kind": "table",
                "name": "armi.cognitive_episodes",
                "logical_owner": "cognitive-episode",
                "activation_step": "M0-S023",
            },
            {
                "kind": "table",
                "name": "armi.cognitive_context_items",
                "logical_owner": "context-snapshot",
                "activation_step": "M0-S023",
            },
            {
                "kind": "table",
                "name": "armi.cognitive_attempts",
                "logical_owner": "cognitive-model-attempt",
                "activation_step": "M0-S024",
            },
            {
                "kind": "table",
                "name": "armi.cognitive_candidate_validations",
                "logical_owner": "candidate-validation",
                "activation_step": "M0-S025",
            },
            {
                "kind": "table",
                "name": "armi.cognitive_candidate_validation_items",
                "logical_owner": "candidate-validation",
                "activation_step": "M0-S025",
            },
            {
                "kind": "table",
                "name": "armi.cognitive_candidate_basis_links",
                "logical_owner": "candidate-validation",
                "activation_step": "M0-S025",
            },
            {
                "kind": "table",
                "name": "armi.subject_commits",
                "logical_owner": "subject-commit",
                "activation_step": "M0-S026",
            },
            {
                "kind": "table",
                "name": "armi.accepted_experiences",
                "logical_owner": "subject-experience",
                "activation_step": "M0-S026",
            },
            {
                "kind": "table",
                "name": "armi.experience_evidence_links",
                "logical_owner": "subject-experience",
                "activation_step": "M0-S026",
            },
            {
                "kind": "table",
                "name": "armi.cognitive_candidate_applications",
                "logical_owner": "subject-commit",
                "activation_step": "M0-S026",
            },
            *[
                {
                    "kind": "table",
                    "name": name,
                    "logical_owner": owner,
                    "activation_step": "M0-S027",
                }
                for name, owner in (
                    ("armi.capabilities", "capability-catalog"),
                    ("armi.capability_requests", "capability-policy"),
                    ("armi.capability_request_basis_links", "capability-policy"),
                    ("armi.capability_request_decisions", "capability-policy"),
                    ("armi.permission_grants", "capability-policy"),
                )
            ],
            *[
                {
                    "kind": "table",
                    "name": name,
                    "logical_owner": owner,
                    "activation_step": "M0-S028",
                }
                for name, owner in (
                    ("armi.action_intents", "response-intent"),
                    ("armi.action_intent_revisions", "response-intent"),
                    ("armi.formal_no_action_decisions", "subject-no-action"),
                    ("armi.creator_response_operations", "response-admission"),
                )
            ],
            *[
                {
                    "kind": "table",
                    "name": name,
                    "logical_owner": owner,
                    "activation_step": "M0-S029",
                }
                for name, owner in (
                    ("armi.policy_decisions", "effect-ledger"),
                    ("armi.effects", "effect-ledger"),
                    ("armi.effect_outbox_items", "effect-ledger"),
                )
            ],
            *[
                {
                    "kind": "table",
                    "name": name,
                    "logical_owner": owner,
                    "activation_step": "M0-S030",
                }
                for name, owner in (
                    ("armi.creator_response_deliveries", "creator-response-inbox"),
                    ("armi.effect_attempts", "effect-execution"),
                    ("armi.effect_observations", "effect-execution"),
                )
            ],
            *[
                {
                    "kind": "table",
                    "name": name,
                    "logical_owner": owner,
                    "activation_step": "M0-S033",
                }
                for name, owner in (
                    ("armi.web_observation_requests", "web-observation-custody"),
                    ("armi.observation_attempts", "web-observation-custody"),
                    ("armi.observation_tool_calls", "web-observation-custody"),
                )
            ],
        ],
        "deferred_objects": [
            {"scope": "creator_effect_ui", "activation_step": "M0-S031"},
        ],
        "runtime_upgrade_allowed": False,
        "database_role_manifest": {
            "path": f"schema/{_ROLE_MANIFEST.as_posix()}",
            "sha256": _digest(role_manifest_bytes),
            "activation_step": "M0-S010",
        },
    }


def canonical_manifest_bytes(value: dict[str, object]) -> bytes:
    return rfc8785.dumps(cast(Any, value)) + b"\n"


def generated_files(root: Path) -> dict[Path, bytes]:
    schema_root = root / _SCHEMA_ROOT
    role_manifest = canonical_manifest_bytes(build_role_manifest())
    manifest = canonical_manifest_bytes(build_manifest(schema_root, role_manifest))
    generated = {
        _MANIFEST: manifest,
        _ROLE_MANIFEST: role_manifest,
        _INVARIANTS: _require_text_file(schema_root / _INVARIANTS),
    }
    for migration_path in sorted((schema_root / "migrations").glob("*.sql")):
        relative = migration_path.relative_to(schema_root)
        generated[relative] = _require_text_file(migration_path)
    return generated


def _matches(root: Path, generated: dict[Path, bytes]) -> bool:
    schema_root = root / _SCHEMA_ROOT
    mirror_root = root / _MIRROR_ROOT
    return all(
        (schema_root / relative).is_file()
        and (schema_root / relative).read_bytes() == value
        and (mirror_root / relative).is_file()
        and (mirror_root / relative).read_bytes() == value
        for relative, value in generated.items()
    )


def _write(root: Path, generated: dict[Path, bytes]) -> None:
    for base in (root / _SCHEMA_ROOT, root / _MIRROR_ROOT):
        for relative, value in generated.items():
            destination = base / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(value)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        generated = generated_files(root)
        if args.write:
            _write(root, generated)
        else:
            temporary_root = root / ".tmp"
            temporary_root.mkdir(exist_ok=True)
            with tempfile.TemporaryDirectory(
                prefix="schema-", dir=temporary_root
            ) as path:
                scratch = Path(path)
                for relative, value in generated.items():
                    target = scratch / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(value)
                if {
                    relative: (scratch / relative).read_bytes()
                    for relative in generated
                } != generated or not _matches(root, generated):
                    print(
                        "DB-MANIFEST-DRIFT: schema artifacts drifted", file=sys.stderr
                    )
                    return 1
    except (OSError, ValueError, json.JSONDecodeError) as error:
        code = str(error) if str(error).startswith("DB-") else "DB-MANIFEST-DRIFT"
        print(f"{code}: schema artifacts are invalid", file=sys.stderr)
        return 1
    print("schema-artifacts: written" if args.write else "schema-artifacts: verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
