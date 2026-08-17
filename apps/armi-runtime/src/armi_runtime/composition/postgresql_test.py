"""Public PostgreSQL test composition for cross-module scenarios.

Root integration tests enter through this composition root.  Owner-private
repositories remain reachable only from their own distribution bootstrap.
"""

# pyright: reportUnusedImport=false

from armi_activity.bootstrap import bootstrap_activity, bootstrap_activity_cognition
from armi_artifact_store.bootstrap import bootstrap_artifact_catalog
from armi_attention.bootstrap import (
    bootstrap_opportunity,
    bootstrap_opportunity_admission,
    bootstrap_opportunity_cognition,
    bootstrap_opportunity_sleep,
    bootstrap_opportunity_transition,
)
from armi_capability.bootstrap import bootstrap_capability
from armi_codex.bootstrap import (
    bootstrap_codex_commit,
    bootstrap_codex_read_ports,
    bootstrap_codex_timeline_projection,
    compose_codex_task_source_gateway,
)
from armi_cognition.bootstrap import (
    bootstrap_cognition_change_set_codec,
    bootstrap_cognition_operation,
    bootstrap_cognition_subject_commit,
    build_candidate_schema,
    build_model_request_bytes,
    check_model_request,
    compose_candidate_validation_context,
    compose_deterministic_candidate_validator,
    load_active_model_binding,
    parse_model_candidate,
)
from armi_data_rights.bootstrap import bootstrap_data_rights_core
from armi_effect.bootstrap import (
    bootstrap_effect_codex_lifecycle,
    bootstrap_effect_grant_cancellation,
    bootstrap_effect_operation_read,
    bootstrap_expression_effect_registration,
    compose_effect_dispatch_repository,
    compose_effect_ledger_repository,
    compose_local_inbox,
    compose_response_admission_repository,
)
from armi_evidence.bootstrap import bootstrap_evidence
from armi_experience.bootstrap import bootstrap_experience_owner
from armi_expression.bootstrap import (
    bootstrap_expression,
    bootstrap_expression_action_ports,
)
from armi_interaction.bootstrap import (
    bootstrap_interaction_action_ports,
    bootstrap_interaction_birth,
    bootstrap_interaction_identity,
    bootstrap_interaction_subject_commit,
    compose_creator_input_repository,
    compose_external_message_input_repository,
    compose_external_message_input_service,
    compose_interaction_perception,
    compose_other_human_input_repository,
    compose_scene_timeline_query,
)
from armi_material.bootstrap import bootstrap_material, bootstrap_material_cognition
from armi_memory.bootstrap import bootstrap_memory, bootstrap_memory_cognition
from armi_mood.bootstrap import bootstrap_mood, bootstrap_mood_cognition
from armi_perception.bootstrap import compose_external_content_pipeline
from armi_prompt.bootstrap import bootstrap_prompt, bootstrap_prompt_cognition
from armi_relationship.bootstrap import (
    bootstrap_relationship,
    bootstrap_relationship_cognition,
)
from armi_sleep.bootstrap import bootstrap_sleep, bootstrap_sleep_cognition
from armi_subject_state.bootstrap import (
    bootstrap_subject_state,
    bootstrap_subject_state_cognition,
)
from armi_web_observation.bootstrap import (
    bootstrap_web_observation,
    bootstrap_web_research_commit,
    normalize_web_observation_response,
)

ArtifactCatalogRepository = bootstrap_artifact_catalog
CodexTaskSourceGateway = compose_codex_task_source_gateway
PostgreSQLResponseAdmissionRepository = compose_response_admission_repository
PostgreSQLEffectDispatchRepository = compose_effect_dispatch_repository
PostgreSQLLocalInbox = compose_local_inbox
PostgreSQLEffectLedgerRepository = compose_effect_ledger_repository
CreatorInputRepository = compose_creator_input_repository
ExternalMessageInputService = compose_external_message_input_service
ExternalMessageInputRepository = compose_external_message_input_repository
OtherHumanInputRepository = compose_other_human_input_repository
PostgreSQLInteractionPerception = compose_interaction_perception
PostgreSQLSceneTimelineQuery = compose_scene_timeline_query
ExternalContentPipeline = compose_external_content_pipeline
normalize_full_response = normalize_web_observation_response
build_request_bytes = build_model_request_bytes
candidate_schema = build_candidate_schema
checked_model_request = check_model_request
load_active_binding = load_active_model_binding
parse_candidate = parse_model_candidate
CandidateValidationContext = compose_candidate_validation_context
DeterministicCandidateValidator = compose_deterministic_candidate_validator

__all__ = (
    "ArtifactCatalogRepository",
    "CandidateValidationContext",
    "CodexTaskSourceGateway",
    "CreatorInputRepository",
    "DeterministicCandidateValidator",
    "ExternalContentPipeline",
    "ExternalMessageInputRepository",
    "ExternalMessageInputService",
    "OtherHumanInputRepository",
    "PostgreSQLEffectDispatchRepository",
    "PostgreSQLEffectLedgerRepository",
    "PostgreSQLInteractionPerception",
    "PostgreSQLLocalInbox",
    "PostgreSQLResponseAdmissionRepository",
    "PostgreSQLSceneTimelineQuery",
    "bootstrap_activity",
    "bootstrap_activity_cognition",
    "bootstrap_artifact_catalog",
    "bootstrap_capability",
    "bootstrap_codex_commit",
    "bootstrap_codex_read_ports",
    "bootstrap_codex_timeline_projection",
    "bootstrap_cognition_change_set_codec",
    "bootstrap_cognition_operation",
    "bootstrap_cognition_subject_commit",
    "bootstrap_data_rights_core",
    "bootstrap_effect_codex_lifecycle",
    "bootstrap_effect_grant_cancellation",
    "bootstrap_effect_operation_read",
    "bootstrap_evidence",
    "bootstrap_experience_owner",
    "bootstrap_expression",
    "bootstrap_expression_action_ports",
    "bootstrap_expression_effect_registration",
    "bootstrap_interaction_action_ports",
    "bootstrap_interaction_birth",
    "bootstrap_interaction_identity",
    "bootstrap_interaction_subject_commit",
    "bootstrap_material",
    "bootstrap_material_cognition",
    "bootstrap_memory",
    "bootstrap_memory_cognition",
    "bootstrap_mood",
    "bootstrap_mood_cognition",
    "bootstrap_opportunity",
    "bootstrap_opportunity_admission",
    "bootstrap_opportunity_cognition",
    "bootstrap_opportunity_sleep",
    "bootstrap_opportunity_transition",
    "bootstrap_prompt",
    "bootstrap_prompt_cognition",
    "bootstrap_relationship",
    "bootstrap_relationship_cognition",
    "bootstrap_sleep",
    "bootstrap_sleep_cognition",
    "bootstrap_subject_state",
    "bootstrap_subject_state_cognition",
    "bootstrap_web_observation",
    "bootstrap_web_research_commit",
    "build_request_bytes",
    "candidate_schema",
    "checked_model_request",
    "load_active_binding",
    "normalize_full_response",
    "parse_candidate",
)
