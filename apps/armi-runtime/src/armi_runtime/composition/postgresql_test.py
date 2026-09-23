"""Public PostgreSQL test composition for cross-module scenarios.

Root integration tests enter through this composition root.  Owner-private
repositories remain reachable only from their own distribution bootstrap.
"""

# pyright: reportUnusedImport=false

from armi_activity.bootstrap import bootstrap_activity, bootstrap_activity_cognition
from armi_artifact_store.bootstrap import bootstrap_artifact_catalog
from armi_attention.bootstrap import (
    bootstrap_autonomy,
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
    compose_codex_delegation_repository,
    compose_codex_task_source_gateway,
)
from armi_cognition.bootstrap import (
    bootstrap_appraisal_read,
    bootstrap_cognition_context,
    bootstrap_cognition_exact_life_query,
    bootstrap_cognition_operation,
    bootstrap_cognition_subject_commit,
    bootstrap_context_candidate_read,
    bootstrap_dialogue_decision_record,
    bootstrap_event_appraisals,
    bootstrap_focus,
    bootstrap_sleep_decision_record,
    build_candidate_schema,
    build_model_request_bytes,
    check_model_request,
    compose_candidate_validation_context,
    compose_deterministic_candidate_validator,
    load_active_model_binding,
    parse_model_candidate,
)
from armi_data_rights.bootstrap import (
    compose_creator_export_service as CreatorExportService,
)
from armi_data_rights.bootstrap import (
    compose_data_rights_order_repository as DataRightsOrderRepository,
)
from armi_data_rights.bootstrap import (
    compose_data_rights_order_service as DataRightsOrderService,
)
from armi_data_rights.bootstrap import (
    compose_data_rights_participant as PostgreSQLDataRightsParticipant,
)
from armi_effect.bootstrap import (
    bootstrap_effect_codex_lifecycle,
    bootstrap_effect_intent_read,
    bootstrap_effect_operation_read,
    bootstrap_effect_recovery,
    bootstrap_effect_runtime,
    bootstrap_expression_effect_registration,
    compose_effect_dispatch_repository,
    compose_effect_ledger_repository,
    compose_local_inbox,
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
    bootstrap_interaction_failure_notifications,
    bootstrap_interaction_identity,
    bootstrap_interaction_party_catalog,
    bootstrap_interaction_recovery,
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
from armi_mind.bootstrap import bootstrap_mind, bootstrap_mind_data_rights
from armi_mood.bootstrap import bootstrap_mood as _bootstrap_mood
from armi_mood.bootstrap import bootstrap_mood_data_rights
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

from armi_runtime.composition.database import (
    compose_data_rights_core as bootstrap_data_rights_core,
)


def bootstrap_mood():
    return _bootstrap_mood(assessments=bootstrap_appraisal_read())


ArtifactCatalogRepository = bootstrap_artifact_catalog
CodexTaskSourceGateway = compose_codex_task_source_gateway
PostgreSQLCodexDelegationRepository = compose_codex_delegation_repository
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
    "CreatorExportService",
    "CreatorInputRepository",
    "DataRightsOrderRepository",
    "DataRightsOrderService",
    "DeterministicCandidateValidator",
    "ExternalContentPipeline",
    "ExternalMessageInputRepository",
    "ExternalMessageInputService",
    "OtherHumanInputRepository",
    "PostgreSQLCodexDelegationRepository",
    "PostgreSQLDataRightsParticipant",
    "PostgreSQLEffectDispatchRepository",
    "PostgreSQLEffectLedgerRepository",
    "PostgreSQLInteractionPerception",
    "PostgreSQLLocalInbox",
    "PostgreSQLSceneTimelineQuery",
    "bootstrap_activity",
    "bootstrap_activity_cognition",
    "bootstrap_appraisal_read",
    "bootstrap_artifact_catalog",
    "bootstrap_autonomy",
    "bootstrap_capability",
    "bootstrap_codex_commit",
    "bootstrap_codex_read_ports",
    "bootstrap_codex_timeline_projection",
    "bootstrap_cognition_context",
    "bootstrap_cognition_exact_life_query",
    "bootstrap_cognition_operation",
    "bootstrap_cognition_subject_commit",
    "bootstrap_context_candidate_read",
    "bootstrap_data_rights_core",
    "bootstrap_dialogue_decision_record",
    "bootstrap_effect_codex_lifecycle",
    "bootstrap_effect_intent_read",
    "bootstrap_effect_operation_read",
    "bootstrap_effect_recovery",
    "bootstrap_effect_runtime",
    "bootstrap_event_appraisals",
    "bootstrap_evidence",
    "bootstrap_experience_owner",
    "bootstrap_expression",
    "bootstrap_expression_action_ports",
    "bootstrap_expression_effect_registration",
    "bootstrap_focus",
    "bootstrap_interaction_action_ports",
    "bootstrap_interaction_birth",
    "bootstrap_interaction_failure_notifications",
    "bootstrap_interaction_identity",
    "bootstrap_interaction_party_catalog",
    "bootstrap_interaction_recovery",
    "bootstrap_interaction_subject_commit",
    "bootstrap_material",
    "bootstrap_material_cognition",
    "bootstrap_memory",
    "bootstrap_memory_cognition",
    "bootstrap_mind",
    "bootstrap_mind_data_rights",
    "bootstrap_mood",
    "bootstrap_mood_data_rights",
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
    "bootstrap_sleep_decision_record",
    "bootstrap_subject_state",
    "bootstrap_subject_state_cognition",
    "build_request_bytes",
    "candidate_schema",
    "checked_model_request",
    "compose_interaction_perception",
    "load_active_binding",
    "parse_candidate",
)
