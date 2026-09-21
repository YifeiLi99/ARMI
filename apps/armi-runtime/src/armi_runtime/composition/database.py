"""Explicit database composition for schema status, baseline, and migration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Final
from uuid import UUID

from armi_activity.api import (
    ActivityCognitionPort,
    ActivityCommitPort,
    ActivityReadPort,
)
from armi_activity.bootstrap import (
    ActivityModule,
    bootstrap_activity,
)
from armi_artifact_store.api import ArtifactCatalogPort
from armi_artifact_store.content_store import ContentAddressedArtifactStore
from armi_attention.api import (
    AutonomyPolicy,
    LifeOpportunityFactsPort,
    OpportunityAdmissionPort,
    OpportunityCognitionPort,
    OpportunityCognitionSelectionPort,
    OpportunityContextReadPort,
    OpportunityOperationReadPort,
    OpportunityRuntimePort,
    OpportunityTransitionPort,
)
from armi_attention.bootstrap import (
    bootstrap_opportunity,
    bootstrap_opportunity_admission,
    bootstrap_opportunity_cognition,
    bootstrap_opportunity_transition,
)
from armi_capability.api import (
    CapabilityReadPort,
)
from armi_codex.api import (
    CodexCommitPort,
    CodexContextReadPort,
    CodexDelegationViolation,
    CodexExecutionReadPort,
    CodexRuntimePort,
    CodexTaskSourceReadPort,
)
from armi_codex.bootstrap import (
    CodexReadPorts,
    bootstrap_codex,
    bootstrap_codex_read_ports,
    bootstrap_codex_timeline_projection,
)
from armi_cognition.api import (
    CandidateValidationDiagnostic,
    CognitionContextLifecyclePort,
    CognitionExactLifeQueryPort,
    CognitionFinalizationPort,
    CognitionModelPort,
    CognitionOperationReadPort,
    CognitionRuntimeStatePort,
    CognitionSchemaDocument,
    CognitionSubjectCommitPort,
    CognitionSubmissionPort,
    CognitionWorkerPort,
)
from armi_cognition.bootstrap import (
    bootstrap_cognition_candidate,
    bootstrap_cognition_exact_life_query,
    bootstrap_cognition_model,
    bootstrap_cognition_operation,
    bootstrap_dialogue_decision_record,
    bootstrap_sleep_decision_record,
)
from armi_context.api import (
    ContextCognitionReadPort,
    ContextDialogueReadPort,
    ContextEmbeddingRuntimePort,
    ContextProjectionInvalidationPort,
    ContextRuntimePort,
    EmbeddingAttemptSink,
    EmbeddingBinding,
    EmbeddingFailureSink,
    load_embedding_binding,
)
from armi_context.bootstrap import (
    ContextCandidateReadPorts,
    bootstrap_context,
    bootstrap_context_candidate_read,
    bootstrap_context_dialogue_read,
    bootstrap_context_embedding,
    bootstrap_context_projection_invalidation,
    inspect_context_embedding_storage,
)
from armi_data_rights.api import (
    DataRightsArtifactLifecyclePort,
    DataRightsCognitionGate,
    DataRightsEffectGate,
    DataRightsFencePort,
    DataRightsInteractionGate,
    DataRightsParticipant,
    DataRightsSubjectCommitGate,
    DataRightsVisibilityPort,
)
from armi_data_rights.bootstrap import (
    DataRightsCore,
    DataRightsModule,
    bootstrap_data_rights,
    bootstrap_data_rights_core,
)
from armi_effect.api import (
    ActionAdapterPort,
    EffectCodexArtifactPort,
    EffectOperationReadPort,
    EffectReadPort,
    EffectRuntimePort,
)
from armi_effect.bootstrap import (
    bootstrap_effect_codex_lifecycle,
    bootstrap_effect_intent_read,
    bootstrap_effect_operation_read,
    bootstrap_effect_runtime,
    bootstrap_expression_effect_registration,
)
from armi_evidence.api import EvidenceReadPort, EvidenceSnapshot, EvidenceWritePort
from armi_evidence.bootstrap import (
    EvidenceModule,
    bootstrap_evidence,
)
from armi_experience.api import ExperienceCommitPort, ExperienceLifeRecordPort
from armi_expression.api import (
    ExpressionCommitPort,
    ExpressionIntentReadPort,
    ResponseViolation,
)
from armi_expression.bootstrap import (
    ExpressionModule,
    bootstrap_expression,
    bootstrap_expression_action_ports,
)
from armi_interaction.api import (
    CreatorIdentityContext,
    CreatorInputTransactionPort,
    CreatorInputWakePort,
    CreatorOperationQueryPort,
    InteractionCognitionReadPort,
    InteractionContextReadPort,
    InteractionCreatorTimelineProjectionPort,
    InteractionEffectDeliveryPort,
    InteractionEffectRoutePort,
    InteractionFailureNotificationPort,
    InteractionIdentityPort,
    InteractionIdentityTokenPort,
    InteractionOtherHumanReadPort,
    InteractionPartyCatalogPort,
    InteractionPerceptionPort,
    InteractionSceneTransitionPort,
    InteractionSubjectCommitPort,
    InteractionVoiceResponseReadPort,
)
from armi_interaction.bootstrap import (
    InteractionModule,
    bootstrap_interaction,
    bootstrap_interaction_birth,
    bootstrap_interaction_failure_notifications,
    bootstrap_interaction_identity,
    bootstrap_interaction_party_catalog,
)
from armi_kernel.application import (
    CreatorProjectionNotifier,
    CredentialPort,
    CredentialPurpose,
    ExecutionCustodyPort,
    LifeRecordQueryPort,
    ModelBinding,
    ModelViolation,
    RuntimeFence,
    load_price_catalog,
)
from armi_live_vision.bootstrap import (
    bootstrap_live_vision_commit,
    bootstrap_visual_origin_read,
)
from armi_live_voice.api import LiveVoiceRuntimePort, VoiceCognitionResultPort
from armi_live_voice.bootstrap import bootstrap_live_voice_context_read
from armi_local_control.configuration import ConfigurationViolation
from armi_local_control.runtime_errors import RuntimeViolation
from armi_local_control.semantic_recall_process import SemanticRecallProcessManager
from armi_material.api import (
    MaterialCandidateContextPort,
    MaterialCognitionPort,
    MaterialCommitPort,
    MaterialProjectionPort,
    MaterialReadPort,
)
from armi_material.bootstrap import (
    MaterialModule,
    bootstrap_material,
)
from armi_memory.api import (
    MemoryCandidateContextPort,
    MemoryCognitionPort,
    MemoryCommitPort,
    MemoryProjectionPort,
    MemoryReadPort,
)
from armi_memory.bootstrap import (
    MemoryModule,
    bootstrap_memory,
)
from armi_mind.api import MindCognitionPort, MindCommitPort, MindReadPort
from armi_mind.bootstrap import MindModule, bootstrap_mind
from armi_mood.api import MoodCognitionPort, MoodCommitPort, MoodReadPort
from armi_mood.bootstrap import MoodModule, bootstrap_mood
from armi_perception.api import ExternalMediaFetchPort, PerceptionDiagnostic
from armi_perception.bootstrap import (
    PerceptionModule,
    bootstrap_perception,
)
from armi_prompt.api import (
    PromptCognitionPort,
    PromptCommitPort,
    PromptReadPort,
)
from armi_prompt.bootstrap import (
    PromptModule,
    bootstrap_prompt,
)
from armi_relationship.api import (
    RelationshipCognitionPort,
    RelationshipCommitPort,
    RelationshipPolicyPort,
    RelationshipReadPort,
)
from armi_relationship.bootstrap import (
    RelationshipModule,
    bootstrap_relationship,
)
from armi_runtime_foundation import (
    PostgreSQLRuntimeUnitOfWork,
    PostgreSQLTransaction,
    RuntimeTransactionFailure,
)
from armi_sleep.api import (
    SleepCognitionPort,
    SleepCommitPort,
    SleepMaintenancePort,
    SleepOpportunityPort,
    SleepReadPort,
    SleepRuntimeFactsPort,
)
from armi_sleep.bootstrap import SleepModule, bootstrap_sleep
from armi_subject_state.api import (
    SubjectStateCognitionPort,
    SubjectStateCommitPort,
    SubjectStateReadPort,
)
from armi_subject_state.bootstrap import (
    SubjectStateModule,
    bootstrap_subject_state,
)

from armi_runtime.adapters.model.doubao_speech import DoubaoSpeechRecognizer
from armi_runtime.adapters.model.external_content import (
    VolcengineArkExternalContentRecognizer,
    load_external_recognition_binding,
)
from armi_runtime.adapters.model.local_embedding import (
    LocalLlamaCppEmbeddingAdapter,
)
from armi_runtime.adapters.model.model_clients import ModelClients
from armi_runtime.adapters.persistence.birth import (
    ContinuityState,
    probe_continuity,
)
from armi_runtime.adapters.persistence.durable_work import PostgreSQLDurableWorkGateway
from armi_runtime.adapters.persistence.environment_identity import (
    PostgreSQLEnvironmentIdentity,
)
from armi_runtime.adapters.persistence.execution_custody import (
    PostgreSQLExecutionCustody,
)
from armi_runtime.adapters.persistence.life_records import PostgreSQLLifeRecordQuery
from armi_runtime.adapters.persistence.other_human_records import (
    PostgreSQLOtherHumanRecordQuery,
)
from armi_runtime.adapters.persistence.recovery import (
    PostgreSQLRuntimeRecovery,
)
from armi_runtime.adapters.persistence.runtime_authority import (
    PostgreSQLRuntimeAuthority,
)
from armi_runtime.adapters.persistence.runtime_observability import (
    PostgreSQLRuntimeObservation,
)
from armi_runtime.adapters.persistence.schema_gateway import (
    DatabaseViolation,
    PostgreSQLSchemaGateway,
    SchemaStatus,
)
from armi_runtime.adapters.persistence.unit_of_work import PostgreSQLUnitOfWorkFactory
from armi_runtime.application.action_lifecycle import (
    RuntimeCodexArtifactReference,
)
from armi_runtime.application.cognition_cycle import (
    RuntimeCognitionCycleSelector,
    RuntimeCognitionState,
    RuntimeContextEpisodeAdapter,
)
from armi_runtime.application.operation_assembler import (
    RuntimeCreatorOperationAssembler,
)
from armi_runtime.application.opportunity_origin import RuntimeOpportunityOrigin

from .birth_manifest import (
    packaged_birth_digests,
)
from .config_assets import runtime_config_path
from .data_rights import compose_data_rights_participants
from .environment import PreparedEnvironment
from .exact_life_query_pipeline import (
    ExactLifeQueryPipeline,
    build_exact_life_query_pipeline,
)
from .model_adapter import create_model_adapter
from .owner_roster import RuntimeOwnerRoster
from .subject_commit_pipeline import (
    SubjectCommitPipeline,
    build_subject_commit_pipeline,
)
from .work_wakeup import WorkWakeupBus

RUNTIME_LOCATOR_NAME: Final = "database.runtime"
MIGRATOR_LOCATOR_NAME: Final = "database.migrator"
MODEL_LOCATOR_NAME: Final = "model.ark_api_key"
SPEECH_LOCATOR_NAME: Final = "speech.volc_credentials"
CODEX_LOCATOR_NAME: Final = "codex.auth_json"

_REASON_BY_CODE: Final = {
    "DB-CONNECTION-UNAVAILABLE": "RUNTIME_DATABASE_UNAVAILABLE",
    "DB-PG-VERSION": "RUNTIME_DATABASE_VERSION_MISMATCH",
    "DB-PGVECTOR-IDENTITY": "RUNTIME_DATABASE_IDENTITY_MISMATCH",
    "DB-DATABASE-IDENTITY": "RUNTIME_DATABASE_IDENTITY_MISMATCH",
    "DB-RUNTIME-ROLE-UNSAFE": "RUNTIME_DATABASE_ROLE_UNSAFE",
    "DB-SCHEMA-MISSING": "RUNTIME_SCHEMA_MISSING",
    "DB-SCHEMA-EXISTS": "RUNTIME_SCHEMA_INVALID",
    "DB-SCHEMA-CONTRACT": "RUNTIME_SCHEMA_INVALID",
    "DB-SCHEMA-INVARIANT": "RUNTIME_SCHEMA_INVALID",
    "DB-SCHEMA-RESOURCE": "RUNTIME_SCHEMA_INVALID",
    "DB-ROLE-IDENTITY": "RUNTIME_DATABASE_ROLE_POLICY_INVALID",
    "DB-ROLE-ATTRIBUTES": "RUNTIME_DATABASE_ROLE_POLICY_INVALID",
    "DB-ROLE-MEMBERSHIP": "RUNTIME_DATABASE_ROLE_POLICY_INVALID",
    "DB-ROLE-GRANT": "RUNTIME_DATABASE_ROLE_POLICY_INVALID",
    "DB-ROLE-OWNER": "RUNTIME_DATABASE_ROLE_POLICY_INVALID",
    "DB-ROLE-SEARCH-PATH": "RUNTIME_DATABASE_ROLE_POLICY_INVALID",
    "DB-ROLE-SESSION-DIRTY": "RUNTIME_DATABASE_ROLE_POLICY_INVALID",
    "DB-ROLE-PUBLIC-PRIVILEGE": "RUNTIME_DATABASE_ROLE_POLICY_INVALID",
    "DB-ROLE-SECURITY-DEFINER": "RUNTIME_DATABASE_ROLE_POLICY_INVALID",
    "DB-ROLE-CREDENTIAL-SCOPE": "RUNTIME_DATABASE_ROLE_POLICY_INVALID",
}


def _load_embedding_binding(environment_root: Path | None = None) -> EmbeddingBinding:
    return load_embedding_binding(
        runtime_config_path("model-bindings.yaml", environment_root=environment_root)
    )


def _compose_embedding(prepared: PreparedEnvironment) -> LocalLlamaCppEmbeddingAdapter:
    try:
        endpoint = SemanticRecallProcessManager(prepared.root).endpoint()
    except RuntimeViolation:
        raise ModelViolation("MODEL-EMBEDDING-CONNECTION") from None
    return LocalLlamaCppEmbeddingAdapter(
        binding=_load_embedding_binding(prepared.root),
        base_url=endpoint.base_url,
        api_key=endpoint.api_key,
    )


def _compose_optional_embedding(
    prepared: PreparedEnvironment,
) -> LocalLlamaCppEmbeddingAdapter | None:
    try:
        return _compose_embedding(prepared)
    except ModelViolation:
        return None


def _with_connection(
    prepared: PreparedEnvironment,
    *,
    locator_name: str,
    purpose: str,
    operation: str,
) -> SchemaStatus:
    locator = prepared.effective.config.secret_locators.get(locator_name)
    if locator is None:
        raise DatabaseViolation(
            "DB-CONNECTION-UNAVAILABLE",
            "the required database credential locator is unavailable",
            status="unavailable",
            exit_code=3,
        )
    port: CredentialPort = prepared.credential_port
    try:
        with port.resolve(locator, CredentialPurpose(purpose)) as handle:
            gateway = PostgreSQLSchemaGateway()

            def invoke(value: memoryview) -> SchemaStatus:
                try:
                    conninfo = bytes(value).decode("utf-8")
                except UnicodeDecodeError:
                    raise DatabaseViolation(
                        "DB-CONNECTION-UNAVAILABLE",
                        "the configured PostgreSQL connection is unavailable",
                        status="unavailable",
                        exit_code=3,
                    ) from None
                if operation == "install":
                    return gateway.install(
                        conninfo,
                        environment_id=prepared.effective.config.environment.environment_id,
                    )
                return gateway.status(
                    conninfo,
                    environment_id=prepared.effective.config.environment.environment_id,
                    role_class="runtime",
                )

            return handle.consume(invoke)
    except ConfigurationViolation as error:
        code = (
            "DB-ROLE-CREDENTIAL-SCOPE"
            if error.code == "SEC-SECRET-PURPOSE"
            else "DB-CONNECTION-UNAVAILABLE"
        )
        raise DatabaseViolation(
            code,
            "the configured PostgreSQL connection is unavailable",
            status="unavailable",
            exit_code=3,
        ) from None


def inspect_runtime_schema(prepared: PreparedEnvironment) -> SchemaStatus:
    """Read-only Runtime probe; this path cannot change schema history."""

    return _with_connection(
        prepared,
        locator_name=RUNTIME_LOCATOR_NAME,
        purpose="database.runtime",
        operation="status",
    )


def inspect_operator_schema(prepared: PreparedEnvironment) -> SchemaStatus:
    return _with_connection(
        prepared,
        locator_name=RUNTIME_LOCATOR_NAME,
        purpose="database.status",
        operation="status",
    )


def inspect_semantic_recall_storage(
    prepared: PreparedEnvironment,
) -> dict[str, object]:
    """Read the bounded projection/index health used by semantic-recall status."""

    locator = prepared.effective.config.secret_locators.get(RUNTIME_LOCATOR_NAME)
    if locator is None:
        return {"database_status": "unavailable"}
    try:
        with prepared.credential_port.resolve(
            locator, CredentialPurpose("database.status")
        ) as handle:

            def invoke(value: memoryview) -> dict[str, object]:
                try:
                    conninfo = bytes(value).decode("utf-8")
                except UnicodeDecodeError:
                    return {"database_status": "unavailable"}
                return inspect_context_embedding_storage(conninfo)

            return handle.consume(invoke)
    except ConfigurationViolation:
        return {"database_status": "unavailable"}


def install_operator_schema(prepared: PreparedEnvironment) -> SchemaStatus:
    return _with_connection(
        prepared,
        locator_name=MIGRATOR_LOCATOR_NAME,
        purpose="database.migrator",
        operation="install",
    )


def reset_operator_schema(prepared: PreparedEnvironment) -> None:
    locator = prepared.effective.config.secret_locators.get(MIGRATOR_LOCATOR_NAME)
    if locator is None:
        raise DatabaseViolation(
            "DB-CONNECTION-UNAVAILABLE",
            "the required database credential locator is unavailable",
            status="unavailable",
            exit_code=3,
        )
    try:
        with prepared.credential_port.resolve(
            locator, CredentialPurpose("database.migrator")
        ) as handle:

            def invoke(value: memoryview) -> None:
                try:
                    conninfo = bytes(value).decode("utf-8")
                except UnicodeDecodeError:
                    raise DatabaseViolation(
                        "DB-CONNECTION-UNAVAILABLE",
                        "the configured PostgreSQL connection is unavailable",
                        status="unavailable",
                        exit_code=3,
                    ) from None
                PostgreSQLSchemaGateway().reset(
                    conninfo,
                    environment_id=prepared.effective.config.environment.environment_id,
                )

            handle.consume(invoke)
    except ConfigurationViolation as error:
        code = (
            "DB-ROLE-CREDENTIAL-SCOPE"
            if error.code == "SEC-SECRET-PURPOSE"
            else "DB-CONNECTION-UNAVAILABLE"
        )
        raise DatabaseViolation(
            code,
            "the configured PostgreSQL connection is unavailable",
            status="unavailable",
            exit_code=3,
        ) from None


def runtime_database_reason(prepared: PreparedEnvironment) -> tuple[str, ...]:
    try:
        inspect_runtime_schema(prepared)
    except DatabaseViolation as error:
        return (_REASON_BY_CODE.get(error.code, "RUNTIME_SCHEMA_INVALID"),)
    return ()


def inspect_runtime_continuity(prepared: PreparedEnvironment) -> ContinuityState:
    locator = prepared.effective.config.secret_locators.get(RUNTIME_LOCATOR_NAME)
    if locator is None:
        return ContinuityState.INVALID
    digests = packaged_birth_digests()
    try:
        with prepared.credential_port.resolve(
            locator,
            CredentialPurpose("database.runtime"),
        ) as handle:

            def invoke(value: memoryview) -> ContinuityState:
                try:
                    conninfo = bytes(value).decode("utf-8")
                except UnicodeDecodeError:
                    return ContinuityState.INVALID
                state = probe_continuity(
                    conninfo,
                    birth_contract_digest=digests["birth_contract_digest"],
                    interaction=bootstrap_interaction_birth(),
                    subject_state=bootstrap_subject_state().birth,
                    mind=bootstrap_mind().birth,
                    mood=bootstrap_mood().birth,
                    prompts=bootstrap_prompt().birth,
                )
                return state

            return handle.consume(invoke)
    except ConfigurationViolation:
        return ContinuityState.INVALID


def compose_runtime_observation(
    unit_of_work_factory: PostgreSQLUnitOfWorkFactory,
    *,
    effects: EffectReadPort,
    artifacts: ArtifactCatalogPort,
) -> PostgreSQLRuntimeObservation:
    """Resolve the Runtime credential for the private read-only sampler."""

    return PostgreSQLRuntimeObservation(
        unit_of_work_factory,
        effects=effects,
        artifacts=artifacts,
    )


async def inspect_creator_context(
    unit_of_work_factory: PostgreSQLUnitOfWorkFactory,
    *,
    subject_id: UUID,
    identity: InteractionIdentityPort,
) -> CreatorIdentityContext | None:
    """Read the unique born Creator through the Interaction owner."""

    async with unit_of_work_factory.unit_of_work(read_only=True) as unit:
        return await identity.creator_context(
            unit.transaction,
            subject_id=subject_id,
        )


def compose_evidence_module() -> EvidenceModule:
    """Bind the one active accepted-evidence owner implementation."""

    return bootstrap_evidence()


def compose_opportunity_admission() -> OpportunityAdmissionPort:
    """Bind the transaction-scoped Opportunity owner port once."""

    return bootstrap_opportunity_admission()


def compose_creator_operation_query(
    *,
    unit_of_work_factory: PostgreSQLUnitOfWorkFactory,
    creator_party_id: UUID,
    interaction: CreatorInputTransactionPort,
    evidence: EvidenceReadPort,
    expression: ExpressionIntentReadPort,
    codex: CodexTaskSourceReadPort,
    codex_executions: CodexExecutionReadPort,
    opportunity: OpportunityOperationReadPort,
    cognition: CognitionOperationReadPort,
    effect: EffectOperationReadPort,
) -> CreatorOperationQueryPort:
    return RuntimeCreatorOperationAssembler(
        factory=unit_of_work_factory,
        creator_party_id=creator_party_id,
        opportunity=opportunity,
        cognition=cognition,
        interaction=interaction,
        evidence=evidence,
        expression=expression,
        effect=effect,
        codex=codex,
        codex_executions=codex_executions,
    )


def compose_interaction_module(
    prepared: PreparedEnvironment,
    *,
    unit_of_work_factory: PostgreSQLUnitOfWorkFactory,
    subject_id: UUID,
    creator_party_id: UUID,
    cursor_key: bytes,
    notifier: CreatorProjectionNotifier | None,
    subject_state_read: SubjectStateReadPort,
    evidence: EvidenceWritePort,
    evidence_read: EvidenceReadPort,
    opportunity: OpportunityAdmissionPort,
    data_rights: DataRightsInteractionGate,
    custody: ExecutionCustodyPort,
    visibility: DataRightsVisibilityPort,
    identity: InteractionIdentityPort,
    identity_tokens: InteractionIdentityTokenPort,
    catalog: ArtifactCatalogPort,
    timeline_projections: InteractionCreatorTimelineProjectionPort,
    voice_responses: InteractionVoiceResponseReadPort,
    sleep_maintenance: SleepMaintenancePort,
    wakeups: WorkWakeupBus | None = None,
    diagnostic: Callable[[str], None] | None = None,
    fault_injector: Callable[[str], None] | None = None,
) -> InteractionModule:
    """Resolve and bind the one active interaction owner implementation."""

    config = prepared.effective.config
    return bootstrap_interaction(
        unit_of_work_factory,
        environment_id=config.environment.environment_id,
        subject_id=subject_id,
        creator_party_id=creator_party_id,
        cursor_key=cursor_key,
        storage=_artifact_storage(prepared, unit_of_work_factory, catalog),
        codex_task_projection=bootstrap_codex_timeline_projection(),
        catalog=catalog,
        data_rights=data_rights,
        custody=custody,
        visibility=visibility,
        timeline_projections=timeline_projections,
        voice_responses=voice_responses,
        identity=identity,
        identity_tokens=identity_tokens,
        subject_state=subject_state_read,
        maintenance_wake=_RuntimeCreatorInputWake(sleep_maintenance),
        evidence=evidence,
        evidence_read=evidence_read,
        opportunity=opportunity,
        notifier=notifier,
        wakeups=wakeups,
        diagnostic=diagnostic,
        fault_injector=fault_injector,
    )


class _RuntimeCreatorInputWake(CreatorInputWakePort):
    __slots__ = ("_maintenance",)

    def __init__(self, maintenance: SleepMaintenancePort) -> None:
        self._maintenance = maintenance

    async def register_creator_input(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        source_ref: UUID,
    ) -> None:
        await self._maintenance.request_creator_input_wake(
            unit_of_work,
            source_ref=source_ref,
        )


def compose_activity_module(
    unit_of_work_factory: PostgreSQLUnitOfWorkFactory,
    *,
    subject_id: UUID,
    creator_party_id: UUID,
    environment_id: UUID,
    cursor_key: bytes,
    subject_state: SubjectStateReadPort,
) -> ActivityModule:
    """Resolve and bind the one active Activity owner implementation."""

    return bootstrap_activity(
        unit_of_work_factory,
        subject_id=subject_id,
        creator_party_id=creator_party_id,
        environment_id=environment_id,
        cursor_key=cursor_key,
        focus=subject_state,
    )


def compose_mind_module() -> MindModule:
    return bootstrap_mind()


def compose_subject_state_module() -> SubjectStateModule:
    """Bind the Self and life-mode owner."""

    return bootstrap_subject_state()


def compose_mood_module() -> MoodModule:
    """Build the one active in-process mood owner."""

    return bootstrap_mood()


def compose_life_record_query(
    unit_of_work_factory: PostgreSQLUnitOfWorkFactory,
    *,
    environment_id: UUID,
    creator_party_id: UUID,
    subject_id: UUID,
    cursor_key: bytes,
    activity_read: ActivityReadPort,
    memory_read: MemoryReadPort,
    material_read: MaterialReadPort,
    relationship_read: RelationshipReadPort,
    subject_state_read: SubjectStateReadPort,
    visibility: DataRightsVisibilityPort,
    experiences: ExperienceLifeRecordPort,
) -> PostgreSQLLifeRecordQuery:
    """Resolve the shared read-only exact-life and memory projection."""

    return PostgreSQLLifeRecordQuery(
        unit_of_work_factory,
        environment_id=environment_id,
        creator_party_id=creator_party_id,
        subject_id=subject_id,
        cursor_key=cursor_key,
        activities=activity_read,
        materials=material_read,
        memories=memory_read,
        relationships=relationship_read,
        subject_state=subject_state_read,
        visibility=visibility,
        experiences=experiences,
    )


def compose_material_module(
    unit_of_work_factory: PostgreSQLUnitOfWorkFactory,
    *,
    subject_id: UUID,
    data_root: Path,
    max_object_bytes: int,
    catalog: ArtifactCatalogPort,
) -> MaterialModule:
    """Resolve and bind the one active life-material owner implementation."""

    return bootstrap_material(
        unit_of_work_factory,
        catalog=catalog,
        subject_id=subject_id,
        data_root=data_root,
        max_object_bytes=max_object_bytes,
    )


def compose_other_human_record_query(
    unit_of_work_factory: PostgreSQLUnitOfWorkFactory,
    *,
    environment_id: UUID,
    cursor_key: bytes,
    data_root: Path,
    max_object_bytes: int,
    visibility: DataRightsVisibilityPort,
    interaction: InteractionOtherHumanReadPort,
    evidence: EvidenceReadPort,
    effect: EffectOperationReadPort,
    catalog: ArtifactCatalogPort,
) -> PostgreSQLOtherHumanRecordQuery:
    """Resolve the read-only Creator record projection for other humans."""

    return PostgreSQLOtherHumanRecordQuery(
        unit_of_work_factory,
        environment_id=environment_id,
        cursor_key=cursor_key,
        data_root=data_root,
        max_object_bytes=max_object_bytes,
        visibility=visibility,
        interaction=interaction,
        evidence=evidence,
        effect=effect,
        catalog=catalog,
    )


def compose_exact_life_query_pipeline(
    prepared: PreparedEnvironment,
    *,
    unit_of_work_factory: PostgreSQLUnitOfWorkFactory,
    query: LifeRecordQueryPort,
    cognition: CognitionExactLifeQueryPort,
    opportunity: OpportunityAdmissionPort,
    catalog: ArtifactCatalogPort,
    wakeups: WorkWakeupBus | None = None,
    diagnostic: Callable[[str], None] | None = None,
    voice: LiveVoiceRuntimePort | None = None,
) -> ExactLifeQueryPipeline:
    config = prepared.effective.config
    return build_exact_life_query_pipeline(
        unit_of_work_factory,
        data_root=prepared.data_root,
        max_object_bytes=config.artifacts.max_object_bytes,
        orphan_grace_seconds=config.artifacts.orphan_grace_seconds,
        catalog=catalog,
        query=query,
        cognition=cognition,
        opportunity=opportunity,
        wakeups=wakeups,
        diagnostic=diagnostic,
        failure_notification=_opportunity_failure_notification(
            prepared, unit_of_work_factory, catalog, diagnostic, voice
        ),
    )


def compose_cognition_exact_life_query() -> CognitionExactLifeQueryPort:
    return bootstrap_cognition_exact_life_query()


def compose_relationship_module(
    unit_of_work_factory: PostgreSQLUnitOfWorkFactory,
    *,
    subject_id: UUID,
    creator_party_id: UUID,
    environment_id: UUID,
    cursor_key: bytes,
    visibility: DataRightsVisibilityPort,
) -> RelationshipModule:
    """Resolve and bind the one active relationship owner implementation."""

    return bootstrap_relationship(
        unit_of_work_factory,
        subject_id=subject_id,
        creator_party_id=creator_party_id,
        environment_id=environment_id,
        cursor_key=cursor_key,
        visibility=visibility,
    )


def compose_runtime_unit_of_work_factory(
    prepared: PreparedEnvironment,
    *,
    authority_admission: Callable[[], RuntimeFence],
) -> PostgreSQLUnitOfWorkFactory:
    """Resolve the sole normal Runtime PostgreSQL unit-of-work pool."""

    locator = prepared.effective.config.secret_locators.get(RUNTIME_LOCATOR_NAME)
    if locator is None:
        raise DatabaseViolation(
            "DB-ROLE-CREDENTIAL-SCOPE",
            "the configured PostgreSQL connection is unavailable",
            status="unavailable",
            exit_code=3,
        )
    try:
        with prepared.credential_port.resolve(
            locator,
            CredentialPurpose("database.runtime"),
        ) as handle:

            def create(value: memoryview) -> PostgreSQLUnitOfWorkFactory:
                try:
                    conninfo = bytes(value).decode("utf-8")
                except UnicodeDecodeError:
                    raise DatabaseViolation(
                        "DB-ROLE-CREDENTIAL-SCOPE",
                        "the configured PostgreSQL connection is unavailable",
                        status="unavailable",
                        exit_code=3,
                    ) from None
                config = prepared.effective.config
                return PostgreSQLUnitOfWorkFactory(
                    conninfo,
                    environment_id=config.environment.environment_id,
                    pool_min=config.database.pool_min,
                    pool_max=config.database.pool_max,
                    acquire_timeout_seconds=config.database.pool_acquire_timeout_seconds,
                    statement_timeout_seconds=config.database.statement_timeout_seconds,
                    authority_admission=authority_admission,
                )

            return handle.consume(create)
    except ConfigurationViolation:
        raise DatabaseViolation(
            "DB-ROLE-CREDENTIAL-SCOPE",
            "the configured PostgreSQL connection is unavailable",
            status="unavailable",
            exit_code=3,
        ) from None


def compose_memory_module(
    unit_of_work_factory: PostgreSQLUnitOfWorkFactory,
    *,
    environment_id: UUID,
    creator_party_id: UUID,
    subject_id: UUID,
    cursor_key: bytes,
    visibility: DataRightsVisibilityPort,
) -> MemoryModule:
    """Resolve and bind the one active subjective-memory owner implementation."""

    return bootstrap_memory(
        unit_of_work_factory,
        environment_id=environment_id,
        creator_party_id=creator_party_id,
        subject_id=subject_id,
        cursor_key=cursor_key,
        visibility=visibility,
    )


def compose_sleep_module(
    unit_of_work_factory: PostgreSQLUnitOfWorkFactory,
    *,
    subject_id: UUID,
    creator_party_id: UUID,
    environment_id: UUID,
    cursor_key: bytes,
    runtime_facts: SleepRuntimeFactsPort,
    opportunities: SleepOpportunityPort,
) -> SleepModule:
    """Resolve and bind the one active sleep owner implementation."""

    return bootstrap_sleep(
        unit_of_work_factory,
        decisions=bootstrap_sleep_decision_record(),
        subject_id=subject_id,
        creator_party_id=creator_party_id,
        environment_id=environment_id,
        cursor_key=cursor_key,
        runtime_facts=runtime_facts,
        opportunities=opportunities,
    )


def compose_runtime_authority(
    prepared: PreparedEnvironment,
) -> PostgreSQLRuntimeAuthority:
    """Resolve only the Runtime DB credential and construct the authority port."""

    locator = prepared.effective.config.secret_locators.get(RUNTIME_LOCATOR_NAME)
    if locator is None:
        raise DatabaseViolation(
            "DB-CONNECTION-UNAVAILABLE",
            "the required database credential locator is unavailable",
            status="unavailable",
            exit_code=3,
        )
    try:
        with prepared.credential_port.resolve(
            locator,
            CredentialPurpose("database.runtime"),
        ) as handle:

            def create(value: memoryview) -> PostgreSQLRuntimeAuthority:
                try:
                    conninfo = bytes(value).decode("utf-8")
                except UnicodeDecodeError:
                    raise DatabaseViolation(
                        "DB-CONNECTION-UNAVAILABLE",
                        "the configured PostgreSQL connection is unavailable",
                        status="unavailable",
                        exit_code=3,
                    ) from None
                config = prepared.effective.config
                return PostgreSQLRuntimeAuthority(
                    conninfo,
                    environment_id=config.environment.environment_id,
                    pool_timeout_seconds=(config.database.pool_acquire_timeout_seconds),
                    statement_timeout_seconds=(
                        config.database.statement_timeout_seconds
                    ),
                )

            return handle.consume(create)
    except ConfigurationViolation:
        raise DatabaseViolation(
            "DB-ROLE-CREDENTIAL-SCOPE",
            "the configured PostgreSQL connection is unavailable",
            status="unavailable",
            exit_code=3,
        ) from None


def compose_execution_custody(
    prepared: PreparedEnvironment,
) -> PostgreSQLExecutionCustody:
    """Construct the dedicated lazy pool used by session-level slow-I/O fences."""

    locator = prepared.effective.config.secret_locators.get(RUNTIME_LOCATOR_NAME)
    if locator is None:
        raise DatabaseViolation(
            "DB-CONNECTION-UNAVAILABLE",
            "the required database credential locator is unavailable",
            status="unavailable",
            exit_code=3,
        )
    try:
        with prepared.credential_port.resolve(
            locator,
            CredentialPurpose("database.runtime"),
        ) as handle:

            def create(value: memoryview) -> PostgreSQLExecutionCustody:
                try:
                    conninfo = bytes(value).decode("utf-8")
                except UnicodeDecodeError:
                    raise DatabaseViolation(
                        "DB-CONNECTION-UNAVAILABLE",
                        "the configured PostgreSQL connection is unavailable",
                        status="unavailable",
                        exit_code=3,
                    ) from None
                config = prepared.effective.config
                return PostgreSQLExecutionCustody(
                    conninfo,
                    environment_id=config.environment.environment_id,
                    pool_max=config.database.pool_max,
                    pool_timeout_seconds=(config.database.pool_acquire_timeout_seconds),
                )

            return handle.consume(create)
    except ConfigurationViolation:
        raise DatabaseViolation(
            "DB-ROLE-CREDENTIAL-SCOPE",
            "the configured PostgreSQL connection is unavailable",
            status="unavailable",
            exit_code=3,
        ) from None


def compose_perception_module(
    prepared: PreparedEnvironment,
    *,
    unit_of_work_factory: PostgreSQLUnitOfWorkFactory,
    fetch: ExternalMediaFetchPort,
    evidence: EvidenceWritePort,
    evidence_read: EvidenceReadPort,
    interaction: InteractionPerceptionPort,
    data_rights: DataRightsFencePort,
    opportunity: OpportunityAdmissionPort,
    catalog: ArtifactCatalogPort,
    wakeups: WorkWakeupBus,
    diagnostic: PerceptionDiagnostic | None = None,
) -> PerceptionModule:
    model_locator = prepared.effective.config.secret_locators.get(MODEL_LOCATOR_NAME)
    speech_locator = prepared.effective.config.secret_locators.get(SPEECH_LOCATOR_NAME)
    from .perception_availability import UnavailableMediaRecognizer

    try:
        recognition_binding = load_external_recognition_binding(
            runtime_config_path("model-bindings.yaml", environment_root=prepared.root)
        )
        return bootstrap_perception(
            prices=load_price_catalog(
                runtime_config_path(
                    "provider-pricing.yaml", environment_root=prepared.root
                )
            ),
            failure_notifications=_interaction_failure_notifications(
                prepared, unit_of_work_factory, catalog, diagnostic
            ),
            unit_of_work_factory=unit_of_work_factory,
            storage=_artifact_storage(prepared, unit_of_work_factory, catalog),
            catalog=catalog,
            work=PostgreSQLDurableWorkGateway(unit_of_work_factory),
            evidence=evidence,
            evidence_read=evidence_read,
            interaction=interaction,
            data_rights=data_rights,
            opportunity=opportunity,
            fetch=fetch,
            ark_recognizer=UnavailableMediaRecognizer(recognition_binding.target_for)
            if model_locator is None
            else VolcengineArkExternalContentRecognizer(
                credential_port=prepared.credential_port,
                locator=model_locator,
                binding=recognition_binding.ark,
            ),
            speech_recognizer=UnavailableMediaRecognizer(recognition_binding.target_for)
            if speech_locator is None
            else DoubaoSpeechRecognizer(
                credential_port=prepared.credential_port,
                locator=speech_locator,
                binding=recognition_binding.speech,
            ),
            target_for=recognition_binding.target_for,
            wakeups=wakeups,
            diagnostic=diagnostic,
        )
    except ConfigurationViolation:
        raise ModelViolation("MODEL-CREDENTIAL") from None
    except ValueError:
        raise ModelViolation("MODEL-BINDING-MANIFEST") from None


def compose_prompt_module(
    prepared: PreparedEnvironment,
    *,
    unit_of_work_factory: PostgreSQLUnitOfWorkFactory,
    subject_id: UUID,
    creator_party_id: UUID,
    catalog: ArtifactCatalogPort,
) -> PromptModule:
    """Resolve the Runtime credential for the T-04 Creator Prompt owner."""

    return bootstrap_prompt(
        subject_id=subject_id,
        creator_party_id=creator_party_id,
        storage=_artifact_storage(prepared, unit_of_work_factory, catalog),
        catalog=catalog,
        unit_of_work_factory=unit_of_work_factory,
    )


def compose_interaction_identity(
    identity_tokens: InteractionIdentityTokenPort,
) -> InteractionIdentityPort:
    return bootstrap_interaction_identity(identity_tokens)


def compose_data_rights_module(
    prepared: PreparedEnvironment,
    *,
    unit_of_work_factory: PostgreSQLUnitOfWorkFactory,
    creator_party_id: UUID,
    core: DataRightsCore,
    business_participants: tuple[DataRightsParticipant, ...],
    catalog: ArtifactCatalogPort,
    parties: InteractionIdentityPort,
    party_roster: InteractionPartyCatalogPort,
    artifact_lifecycle: DataRightsArtifactLifecyclePort,
    execution_custody: ExecutionCustodyPort,
    identity_key: str,
    notifier: CreatorProjectionNotifier | None = None,
) -> DataRightsModule:
    from .data_rights_contracts import DATA_RIGHTS_OWNER_CONTRACTS

    participants = compose_data_rights_participants(
        business=business_participants,
        catalog=catalog,
    )
    return bootstrap_data_rights(
        creator_party_id=creator_party_id,
        custody=execution_custody,
        data_root=prepared.data_root,
        unit_of_work_factory=unit_of_work_factory,
        storage=_artifact_storage(prepared, unit_of_work_factory, catalog),
        lifecycle=artifact_lifecycle,
        core=core,
        parties=parties,
        party_roster=party_roster,
        catalog=catalog,
        participants=participants,
        owner_contracts=DATA_RIGHTS_OWNER_CONTRACTS,
        identity_key=identity_key,
        identity_binding=PostgreSQLEnvironmentIdentity(),
        notifier=notifier,
    )


def compose_data_rights_core() -> DataRightsCore:
    return bootstrap_data_rights_core(parties=bootstrap_interaction_party_catalog())


def compose_context_projection_invalidation() -> ContextProjectionInvalidationPort:
    return bootstrap_context_projection_invalidation()


def compose_context_candidate_read() -> ContextCandidateReadPorts:
    return bootstrap_context_candidate_read()


def compose_life_opportunity_pipeline(
    prepared: PreparedEnvironment,
    *,
    unit_of_work_factory: PostgreSQLUnitOfWorkFactory,
    facts: LifeOpportunityFactsPort,
    activity_read: ActivityReadPort,
    sleep_maintenance: SleepMaintenancePort,
    sleep_read: SleepReadPort,
    subject_state_read: SubjectStateReadPort,
    wakeups: WorkWakeupBus | None = None,
    notifier: CreatorProjectionNotifier | None = None,
) -> OpportunityRuntimePort:
    """Resolve the Runtime credential for the P0-S001 source owner."""

    config = prepared.effective.config
    return bootstrap_opportunity(
        autonomy_policy=AutonomyPolicy(**config.autonomy.model_dump()),
        factory=unit_of_work_factory,
        facts=facts,
        activity_read=activity_read,
        sleep_maintenance=sleep_maintenance,
        sleep_read=sleep_read,
        subject_state_read=subject_state_read,
        wakeups=wakeups,
        notifier=notifier,
        model_concurrency=config.model.concurrency,
        maintenance_consideration_seconds=(
            config.maintenance.consideration_after_seconds
        ),
        maintenance_deadline_seconds=config.maintenance.deadline_after_seconds,
    )


def compose_context_pipeline(
    prepared: PreparedEnvironment,
    *,
    unit_of_work_factory: PostgreSQLUnitOfWorkFactory,
    activity_read: ActivityReadPort,
    capability_read: CapabilityReadPort,
    codex_read: CodexTaskSourceReadPort,
    codex_context: CodexContextReadPort,
    cognition_context: CognitionContextLifecyclePort,
    evidence_read: EvidenceReadPort,
    interaction_context: InteractionContextReadPort,
    dialogue_read: ContextDialogueReadPort,
    interaction_cognition: InteractionCognitionReadPort,
    opportunity_cognition: OpportunityCognitionPort,
    runtime_subjects: RuntimeCognitionState,
    expression_read: ExpressionIntentReadPort,
    effect_read: EffectOperationReadPort,
    data_rights: DataRightsCognitionGate,
    custody: ExecutionCustodyPort,
    memory_read: MemoryReadPort,
    memory_projection: MemoryProjectionPort,
    mood_read: MoodReadPort,
    prompt_read: PromptReadPort,
    material_projection: MaterialProjectionPort,
    relationship_read: RelationshipReadPort,
    sleep_read: SleepReadPort,
    subject_state_read: SubjectStateReadPort,
    mind_read: MindReadPort,
    catalog: ArtifactCatalogPort,
    wakeups: WorkWakeupBus | None = None,
    diagnostic: Callable[[str], None] | None = None,
    voice: LiveVoiceRuntimePort | None = None,
) -> ContextRuntimePort:
    """Resolve the Runtime credential for the active S023 selector and worker."""

    config = prepared.effective.config
    selection = RuntimeCognitionCycleSelector(
        factory=unit_of_work_factory,
        opportunities=opportunity_cognition,
        episodes=cognition_context,
        sleep=sleep_read,
        data_rights=data_rights,
        evidence=evidence_read,
        interaction=interaction_cognition,
        codex_context=codex_context,
        codex_sources=codex_read,
        effects=effect_read,
        expression=expression_read,
        origins=RuntimeOpportunityOrigin(
            opportunities=bootstrap_opportunity_transition(),
            evidence=evidence_read,
            codex=codex_context,
            effects=effect_read,
            expression=expression_read,
        ),
    )
    storage = _artifact_storage(prepared, unit_of_work_factory, catalog)
    return bootstrap_context(
        failure_notification=_cognition_failure_notification(
            prepared, unit_of_work_factory, catalog, diagnostic, voice
        ),
        factory=unit_of_work_factory,
        storage=storage,
        catalog=catalog,
        work=PostgreSQLDurableWorkGateway(unit_of_work_factory),
        custody=custody,
        activity_read=activity_read,
        capability_read=capability_read,
        memory_read=memory_read,
        memory_projection=memory_projection,
        mood_read=mood_read,
        prompt_read=prompt_read,
        material_projection=material_projection,
        relationship_read=relationship_read,
        sleep_read=sleep_read,
        subject_state_read=subject_state_read,
        mind_read=mind_read,
        selection=selection,
        episodes=RuntimeContextEpisodeAdapter(cognition_context),
        runtime_subjects=runtime_subjects,
        opportunity_context=opportunity_cognition,
        opportunity_transitions=opportunity_cognition,
        evidence_read=evidence_read,
        interaction_context=interaction_context,
        dialogue_read=dialogue_read,
        codex_read=codex_read,
        wakeups=wakeups,
        diagnostic=diagnostic,
        embedding=(
            _compose_optional_embedding(prepared)
            if config.model.semantic_recall_enabled
            else None
        ),
    )


def compose_context_dialogue_read(
    prepared: PreparedEnvironment,
    *,
    catalog: ArtifactCatalogPort,
    evidence: EvidenceReadPort,
    interaction: InteractionContextReadPort,
    expression: ExpressionIntentReadPort,
    effects: EffectOperationReadPort,
    opportunities: OpportunityTransitionPort,
) -> ContextDialogueReadPort:
    return bootstrap_context_dialogue_read(
        storage=ContentAddressedArtifactStore(
            prepared.data_root / "artifacts",
            max_object_bytes=prepared.effective.config.artifacts.max_object_bytes,
        ),
        catalog=catalog,
        evidence=evidence,
        interaction=interaction,
        expression=expression,
        effects=effects,
        voice=bootstrap_live_voice_context_read(),
        opportunities=opportunities,
    )


def compose_context_embedding_pipeline(
    prepared: PreparedEnvironment,
    *,
    unit_of_work_factory: PostgreSQLUnitOfWorkFactory,
    custody: ExecutionCustodyPort,
    memory_projection: MemoryProjectionPort,
    material_projection: MaterialProjectionPort,
    failure_diagnostic: EmbeddingFailureSink | None = None,
    attempt_diagnostic: EmbeddingAttemptSink | None = None,
) -> ContextEmbeddingRuntimePort:
    return bootstrap_context_embedding(
        factory=unit_of_work_factory,
        storage=ContentAddressedArtifactStore(
            prepared.data_root / "artifacts",
            max_object_bytes=prepared.effective.config.artifacts.max_object_bytes,
        ),
        adapter=_compose_embedding(prepared),
        custody=custody,
        work=PostgreSQLDurableWorkGateway(unit_of_work_factory),
        memories=memory_projection,
        materials=material_projection,
        failure_diagnostic=failure_diagnostic,
        attempt_diagnostic=attempt_diagnostic,
    )


def _interaction_failure_notifications(
    prepared: PreparedEnvironment,
    factory: PostgreSQLUnitOfWorkFactory,
    catalog: ArtifactCatalogPort,
    diagnostic: Callable[[str], None] | None,
    voice: LiveVoiceRuntimePort | None = None,
) -> InteractionFailureNotificationPort:
    async def derived_origin(
        transaction: PostgreSQLTransaction, evidence: EvidenceSnapshot
    ) -> UUID | None:
        if evidence.visual_observation_id is not None:
            episode_id = await bootstrap_visual_origin_read().origin_episode(
                transaction, observation_id=evidence.visual_observation_id
            )
            if episode_id is None:
                return None
            return await bootstrap_cognition_operation().opportunity_for_episode(
                transaction, episode_id=episode_id
            )
        if evidence.codex_verification_id is not None:
            effect_id = (
                await bootstrap_codex_read_ports().context.verification_effect_id(
                    transaction, verification_id=evidence.codex_verification_id
                )
            )
            effect = await bootstrap_effect_operation_read().by_effect_id(
                transaction, effect_id=effect_id
            )
            if effect is None or effect.action_intent_id is None:
                return None
            intent = await bootstrap_expression_action_ports(
                bootstrap_effect_intent_read(), bootstrap_dialogue_decision_record()
            ).intents.intent_snapshot(
                transaction, action_intent_id=effect.action_intent_id
            )
            return intent.root_opportunity_id
        return None

    async def guarded_derived_origin(
        transaction: PostgreSQLTransaction, evidence: EvidenceSnapshot
    ) -> UUID | None:
        try:
            return await derived_origin(transaction, evidence)
        except CodexDelegationViolation, ResponseViolation:
            if diagnostic is not None:
                diagnostic("interaction.notification.origin_unavailable")
            return None

    async def voice_failure(opportunity_id: UUID) -> None:
        if voice is None:
            return
        async with factory.unit_of_work(read_only=True) as uow:
            turn_id = await bootstrap_live_voice_context_read().turn_for_opportunity(
                uow.transaction,
                opportunity_id=opportunity_id,
            )
        if turn_id is not None:
            await voice.fail_cognition(turn_id=turn_id)

    return bootstrap_interaction_failure_notifications(
        derived_origin=guarded_derived_origin,
        voice_failure=voice_failure if voice is not None else None,
        factory=factory,
        opportunities=bootstrap_opportunity_cognition(),
        evidence=bootstrap_evidence().read,
        diagnostic=diagnostic or (lambda _event: None),
    )


def compose_visual_failure_notification(
    prepared: PreparedEnvironment,
    factory: PostgreSQLUnitOfWorkFactory,
    catalog: ArtifactCatalogPort,
    diagnostic: Callable[[str], None] | None = None,
    voice: LiveVoiceRuntimePort | None = None,
) -> Callable[[UUID, str], Awaitable[None]]:
    notify_episode = _cognition_failure_notification(
        prepared, factory, catalog, diagnostic, voice
    )

    async def notify(observation_id: UUID, code: str) -> None:
        try:
            async with factory.unit_of_work(read_only=True) as unit:
                episode_id = await bootstrap_visual_origin_read().origin_episode(
                    unit.transaction, observation_id=observation_id
                )
            if episode_id is not None:
                await notify_episode(episode_id, code)
        except RuntimeTransactionFailure:
            if diagnostic is not None:
                diagnostic("vision.notification.source_unavailable")

    return notify


def _opportunity_failure_notification(
    prepared: PreparedEnvironment,
    factory: PostgreSQLUnitOfWorkFactory,
    catalog: ArtifactCatalogPort,
    diagnostic: Callable[[str], None] | None,
    voice: LiveVoiceRuntimePort | None = None,
) -> Callable[[UUID, str], Awaitable[None]]:
    notifications = _interaction_failure_notifications(
        prepared, factory, catalog, diagnostic, voice
    )

    async def notify(opportunity_id: UUID, code: str) -> None:
        await notifications.notify_failure(
            opportunity_id=opportunity_id, failure_code=code
        )

    return notify


def _cognition_failure_notification(
    prepared: PreparedEnvironment,
    factory: PostgreSQLUnitOfWorkFactory,
    catalog: ArtifactCatalogPort,
    diagnostic: Callable[[str], None] | None,
    voice: LiveVoiceRuntimePort | None = None,
) -> Callable[[UUID, str], Awaitable[None]]:
    notifications = _interaction_failure_notifications(
        prepared, factory, catalog, diagnostic, voice
    )
    cognition = bootstrap_cognition_operation()

    async def notify(episode_id: UUID, code: str) -> None:
        try:
            async with factory.unit_of_work(read_only=True) as uow:
                opportunity_id = await cognition.opportunity_for_episode(
                    uow.transaction,
                    episode_id=episode_id,
                )
        except RuntimeTransactionFailure:
            if diagnostic is not None:
                diagnostic("cognition.notification.source_unavailable")
            return
        if opportunity_id is not None:
            await notifications.notify_failure(
                opportunity_id=opportunity_id, failure_code=code
            )

    return notify


def compose_model_pipeline(
    prepared: PreparedEnvironment,
    *,
    clients: ModelClients,
    unit_of_work_factory: PostgreSQLUnitOfWorkFactory,
    context: ContextCognitionReadPort,
    opportunities: OpportunityCognitionSelectionPort,
    catalog: ArtifactCatalogPort,
    custody: ExecutionCustodyPort,
    finalization: CognitionFinalizationPort,
    wakeups: WorkWakeupBus | None = None,
    diagnostic: Callable[[str], None] | None = None,
    voice: LiveVoiceRuntimePort | None = None,
) -> CognitionWorkerPort:
    """Resolve the Runtime and model credentials for the active S024 worker."""

    config = prepared.effective.config

    def adapter_factory(
        *,
        binding: ModelBinding,
        candidate_schema: CognitionSchemaDocument,
        instructions: str,
        schema_name: str,
    ) -> CognitionModelPort:
        locator_name = {
            "volcengine_ark": MODEL_LOCATOR_NAME,
            "qwen": "model.qwen_api_key",
            "deepseek": "model.deepseek_api_key",
        }[binding.provider]
        model_locator = config.secret_locators.get(locator_name)
        if model_locator is None and binding.profile != "creator_voice_act":
            raise ModelViolation("MODEL-CREDENTIAL")
        return create_model_adapter(
            clients=clients,
            binding=binding,
            credential_port=prepared.credential_port,
            locator=model_locator,
            candidate_schema=candidate_schema,
            instructions=instructions,
            schema_name=schema_name,
        )

    return bootstrap_cognition_model(
        prices=load_price_catalog(
            runtime_config_path("provider-pricing.yaml", environment_root=prepared.root)
        ),
        failure_notification=_cognition_failure_notification(
            prepared, unit_of_work_factory, catalog, diagnostic, voice
        ),
        factory=unit_of_work_factory,
        storage=_artifact_storage(prepared, unit_of_work_factory, catalog),
        catalog=catalog,
        context=context,
        opportunities=opportunities,
        work=PostgreSQLDurableWorkGateway(unit_of_work_factory),
        custody=custody,
        finalization=finalization,
        adapter_factory=adapter_factory,
        binding_path=runtime_config_path(
            "model-bindings.yaml", environment_root=prepared.root
        ),
        wakeups=wakeups,
        diagnostic=diagnostic,
    )


def compose_candidate_validation_pipeline(
    prepared: PreparedEnvironment,
    *,
    unit_of_work_factory: PostgreSQLUnitOfWorkFactory,
    submission: CognitionSubmissionPort,
    activity_cognition: ActivityCognitionPort,
    activity_read: ActivityReadPort,
    material_context: MaterialCandidateContextPort,
    memory_context: MemoryCandidateContextPort,
    context: ContextCognitionReadPort,
    runtime_state: CognitionRuntimeStatePort,
    interaction: InteractionCognitionReadPort,
    opportunity_context: OpportunityContextReadPort,
    opportunity_transitions: OpportunityCognitionSelectionPort,
    evidence: EvidenceReadPort,
    codex: CodexTaskSourceReadPort,
    codex_available: Callable[[], bool],
    memory_cognition: MemoryCognitionPort,
    memory_read: MemoryReadPort,
    mood_cognition: MoodCognitionPort,
    mood_read: MoodReadPort,
    prompt_cognition: PromptCognitionPort,
    prompt_read: PromptReadPort,
    material_cognition: MaterialCognitionPort,
    material_read: MaterialReadPort,
    relationship_cognition: RelationshipCognitionPort,
    relationship_read: RelationshipReadPort,
    sleep_cognition: SleepCognitionPort,
    sleep_read: SleepReadPort,
    subject_state_cognition: SubjectStateCognitionPort,
    mind_cognition: MindCognitionPort,
    subject_state_read: SubjectStateReadPort,
    mind_read: MindReadPort,
    catalog: ArtifactCatalogPort,
    visual_sources_active: frozenset[str] = frozenset(),
    diagnostic: Callable[[str], None] | None = None,
    validation_diagnostic: Callable[[CandidateValidationDiagnostic], None]
    | None = None,
    voice: LiveVoiceRuntimePort | None = None,
) -> CognitionFinalizationPort:
    """Resolve the Runtime credential for the active S025 validator."""

    return bootstrap_cognition_candidate(
        failure_notification=_cognition_failure_notification(
            prepared, unit_of_work_factory, catalog, diagnostic, voice
        ),
        factory=unit_of_work_factory,
        storage=_artifact_storage(prepared, unit_of_work_factory, catalog),
        catalog=catalog,
        submission=submission,
        activity_cognition=activity_cognition,
        activity_read=activity_read,
        material_context=material_context,
        memory_context=memory_context,
        context=context,
        runtime_state=runtime_state,
        interaction=interaction,
        opportunity_context=opportunity_context,
        opportunity_transitions=opportunity_transitions,
        evidence=evidence,
        codex=codex,
        codex_available=codex_available,
        memory_cognition=memory_cognition,
        memory_read=memory_read,
        mood_cognition=mood_cognition,
        mood_read=mood_read,
        prompt_cognition=prompt_cognition,
        prompt_read=prompt_read,
        material_cognition=material_cognition,
        material_read=material_read,
        relationship_cognition=relationship_cognition,
        relationship_read=relationship_read,
        sleep_cognition=sleep_cognition,
        sleep_read=sleep_read,
        subject_state_cognition=subject_state_cognition,
        mind_cognition=mind_cognition,
        subject_state_read=subject_state_read,
        mind_read=mind_read,
        visual_sources_active=visual_sources_active,
        diagnostic=diagnostic,
        validation_diagnostic=validation_diagnostic,
    )


def compose_subject_commit_pipeline(
    prepared: PreparedEnvironment,
    *,
    unit_of_work_factory: PostgreSQLUnitOfWorkFactory,
    activity_commit: ActivityCommitPort,
    codex_commit: CodexCommitPort,
    cognition_commit: CognitionSubjectCommitPort,
    experience_commit: ExperienceCommitPort,
    context_projections: ContextProjectionInvalidationPort,
    data_rights: DataRightsSubjectCommitGate,
    evidence: EvidenceWritePort,
    evidence_read: EvidenceReadPort,
    expression_commit: ExpressionCommitPort,
    interaction_commit: InteractionSubjectCommitPort,
    memory_commit: MemoryCommitPort,
    mood_commit: MoodCommitPort,
    opportunity_transition: OpportunityTransitionPort,
    prompt_commit: PromptCommitPort,
    material_commit: MaterialCommitPort,
    relationship_commit: RelationshipCommitPort,
    sleep_commit: SleepCommitPort,
    subject_state_commit: SubjectStateCommitPort,
    mind_commit: MindCommitPort,
    catalog: ArtifactCatalogPort,
    notifier: CreatorProjectionNotifier | None,
    voice_results: VoiceCognitionResultPort | None = None,
    wakeups: WorkWakeupBus | None = None,
    diagnostic: Callable[[str], None] | None = None,
    fault_injector: Callable[[str], None] | None = None,
) -> SubjectCommitPipeline:
    """Resolve the Runtime credential for the sole active T-03 coordinator."""

    config = prepared.effective.config
    return build_subject_commit_pipeline(
        unit_of_work_factory,
        data_root=prepared.data_root,
        max_object_bytes=config.artifacts.max_object_bytes,
        orphan_grace_seconds=config.artifacts.orphan_grace_seconds,
        catalog=catalog,
        activity_commit=activity_commit,
        codex_commit=codex_commit,
        cognition_commit=cognition_commit,
        experience_commit=experience_commit,
        context_projections=context_projections,
        data_rights=data_rights,
        evidence=evidence,
        evidence_read=evidence_read,
        expression_commit=expression_commit,
        interaction_commit=interaction_commit,
        memory_commit=memory_commit,
        mood_commit=mood_commit,
        opportunity_transition=opportunity_transition,
        prompt_commit=prompt_commit,
        material_commit=material_commit,
        relationship_commit=relationship_commit,
        sleep_commit=sleep_commit,
        subject_state_commit=subject_state_commit,
        mind_commit=mind_commit,
        visual_observation_commit=bootstrap_live_vision_commit(),
        notifier=notifier,
        voice_results=voice_results,
        wakeups=wakeups,
        diagnostic=diagnostic,
        fault_injector=fault_injector,
    )


def compose_expression_module(
    *,
    relationship_read: RelationshipReadPort,
    relationship_policy: RelationshipPolicyPort,
    interaction_routes: InteractionEffectRoutePort,
    interaction_scenes: InteractionSceneTransitionPort,
) -> ExpressionModule:
    return bootstrap_expression(
        relationship_read,
        relationship_policy,
        bootstrap_expression_effect_registration(),
        interaction_routes,
        interaction_scenes,
        bootstrap_live_voice_context_read(),
        bootstrap_effect_intent_read(),
        bootstrap_dialogue_decision_record(),
    )


def compose_runtime_recovery(
    prepared: PreparedEnvironment,
    *,
    unit_of_work_factory: PostgreSQLUnitOfWorkFactory,
    authority_admission: Callable[[], RuntimeFence],
    owner_roster: RuntimeOwnerRoster,
    catalog: ArtifactCatalogPort,
) -> PostgreSQLRuntimeRecovery:
    """Resolve the Runtime credential for the fenced startup recovery gateway."""

    config = prepared.effective.config
    return PostgreSQLRuntimeRecovery(
        unit_of_work_factory,
        environment_id=config.environment.environment_id,
        data_root=prepared.data_root,
        max_object_bytes=config.artifacts.max_object_bytes,
        authority_admission=authority_admission,
        participants=owner_roster.recovery,
        expected_owners=owner_roster.expected_recovery_owners,
        catalog=catalog,
    )


def compose_effect_pipeline(
    prepared: PreparedEnvironment,
    *,
    unit_of_work_factory: PostgreSQLUnitOfWorkFactory,
    catalog: ArtifactCatalogPort,
    intents: ExpressionIntentReadPort,
    codex_artifacts: EffectCodexArtifactPort,
    routes: InteractionEffectRoutePort,
    interaction_delivery: InteractionEffectDeliveryPort,
    custody: ExecutionCustodyPort,
    data_rights: DataRightsEffectGate,
    data_rights_fence: DataRightsFencePort,
    runtime_admission: Callable[[], RuntimeFence],
    notifier: CreatorProjectionNotifier | None = None,
    wakeups: WorkWakeupBus,
    diagnostic: Callable[[str], None] | None = None,
    voice: LiveVoiceRuntimePort | None = None,
    fault_injector: Callable[[str], None] | None = None,
    external_message_adapter: ActionAdapterPort | None = None,
    live_voice_adapter: ActionAdapterPort | None = None,
) -> EffectRuntimePort:
    """Resolve the Runtime credential for the S029 T-05 worker."""

    return bootstrap_effect_runtime(
        failure_notifications=_interaction_failure_notifications(
            prepared, unit_of_work_factory, catalog, diagnostic, voice
        ),
        factory=unit_of_work_factory,
        storage=ContentAddressedArtifactStore(
            prepared.data_root / "artifacts",
            max_object_bytes=prepared.effective.config.artifacts.max_object_bytes,
        ),
        intents=intents,
        codex_artifacts=codex_artifacts,
        routes=routes,
        interaction_delivery=interaction_delivery,
        custody=custody,
        data_rights=data_rights,
        data_rights_fence=data_rights_fence,
        runtime_admission=runtime_admission,
        notifier=notifier,
        diagnostic=diagnostic,
        fault_injector=fault_injector,
        external_message_adapter=external_message_adapter,
        live_voice_adapter=live_voice_adapter,
    )


def compose_codex_read_ports() -> CodexReadPorts:
    return bootstrap_codex_read_ports()


def compose_effect_owner_context(
    *,
    codex: CodexReadPorts,
    catalog: ArtifactCatalogPort,
) -> RuntimeCodexArtifactReference:
    return RuntimeCodexArtifactReference(artifacts=catalog, codex=codex.artifacts)


def compose_codex_pipeline(
    prepared: PreparedEnvironment,
    *,
    unit_of_work_factory: PostgreSQLUnitOfWorkFactory,
    creator_party_id: UUID,
    creator_input: CreatorInputTransactionPort,
    evidence: EvidenceWritePort,
    evidence_read: EvidenceReadPort,
    identity: InteractionIdentityPort,
    opportunity: OpportunityAdmissionPort,
    expression: ExpressionIntentReadPort,
    sources: CodexTaskSourceReadPort,
    unavailable_reason: Callable[[], str | None],
    custody: ExecutionCustodyPort,
    data_rights: DataRightsEffectGate,
    interaction_data_rights: DataRightsInteractionGate,
    data_rights_fence: DataRightsFencePort,
    runtime_admission: Callable[[], RuntimeFence],
    catalog: ArtifactCatalogPort,
    notifier: CreatorProjectionNotifier | None = None,
    diagnostic: Callable[[str], None] | None = None,
    voice: LiveVoiceRuntimePort | None = None,
) -> CodexRuntimePort:
    """Compose the one active S039 Codex dispatcher without exposing auth."""

    run_root = prepared.data_root / "codex-runner"
    return bootstrap_codex(
        failure_notification=_opportunity_failure_notification(
            prepared, unit_of_work_factory, catalog, diagnostic, voice
        ),
        factory=unit_of_work_factory,
        storage=_artifact_storage(prepared, unit_of_work_factory, catalog),
        catalog=catalog,
        environment_root=prepared.root,
        run_root=run_root,
        creator_party_id=creator_party_id,
        creator_input=creator_input,
        evidence=evidence,
        evidence_read=evidence_read,
        identity=identity,
        opportunity=opportunity,
        effect=bootstrap_effect_codex_lifecycle(),
        expression=expression,
        sources=sources,
        unavailable_reason=unavailable_reason,
        custody=custody,
        data_rights=data_rights,
        interaction_data_rights=interaction_data_rights,
        data_rights_fence=data_rights_fence,
        runtime_admission=runtime_admission,
        runner_entry_module="armi_runtime.codex_runner_cli",
        notifier=notifier,
        diagnostic=diagnostic,
    )


__all__ = (
    "CODEX_LOCATOR_NAME",
    "MIGRATOR_LOCATOR_NAME",
    "RUNTIME_LOCATOR_NAME",
    "ContinuityState",
    "DatabaseViolation",
    "compose_activity_module",
    "compose_candidate_validation_pipeline",
    "compose_codex_pipeline",
    "compose_codex_read_ports",
    "compose_cognition_exact_life_query",
    "compose_context_dialogue_read",
    "compose_context_pipeline",
    "compose_creator_operation_query",
    "compose_data_rights_core",
    "compose_data_rights_module",
    "compose_effect_owner_context",
    "compose_effect_pipeline",
    "compose_evidence_module",
    "compose_exact_life_query_pipeline",
    "compose_execution_custody",
    "compose_expression_module",
    "compose_interaction_identity",
    "compose_interaction_module",
    "compose_life_opportunity_pipeline",
    "compose_life_record_query",
    "compose_material_module",
    "compose_memory_module",
    "compose_mind_module",
    "compose_model_pipeline",
    "compose_mood_module",
    "compose_opportunity_admission",
    "compose_other_human_record_query",
    "compose_perception_module",
    "compose_prompt_module",
    "compose_relationship_module",
    "compose_runtime_authority",
    "compose_runtime_observation",
    "compose_runtime_recovery",
    "compose_runtime_unit_of_work_factory",
    "compose_sleep_module",
    "compose_subject_commit_pipeline",
    "compose_subject_state_module",
    "inspect_creator_context",
    "inspect_operator_schema",
    "inspect_runtime_continuity",
    "inspect_runtime_schema",
    "inspect_semantic_recall_storage",
    "install_operator_schema",
    "reset_operator_schema",
    "runtime_database_reason",
)


def _artifact_storage(
    prepared: PreparedEnvironment,
    unit_of_work_factory: PostgreSQLUnitOfWorkFactory,
    catalog: ArtifactCatalogPort,
) -> ContentAddressedArtifactStore:
    config = prepared.effective.config.artifacts
    return ContentAddressedArtifactStore(
        prepared.data_root / "artifacts",
        max_object_bytes=config.max_object_bytes,
        publication_catalog=catalog,
        publication_uow_factory=unit_of_work_factory,
        orphan_grace_seconds=config.orphan_grace_seconds,
    )
