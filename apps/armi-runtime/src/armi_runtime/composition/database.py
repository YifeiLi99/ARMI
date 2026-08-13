"""Explicit database composition for schema status, baseline, and migration."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Final, cast
from uuid import UUID

from armi_activity.api import (
    ActivityCognitionPort,
    ActivityCommitPort,
    ActivityReadPort,
)
from armi_activity.bootstrap import (
    ActivityModule,
    bootstrap_activity,
    bootstrap_activity_recovery,
)
from armi_artifact_store.bootstrap import bootstrap_artifact_catalog
from armi_artifact_store.content_store import ContentAddressedArtifactStore
from armi_capability.api import (
    CapabilityActionAuthorizationPort,
    CapabilityAdmissionPort,
    CapabilityCommitPort,
    CapabilityDispatchAuthorizationPort,
    CapabilityOperationReadPort,
    CapabilityReadPort,
)
from armi_capability.bootstrap import (
    CapabilityModule,
    bootstrap_capability,
    bootstrap_capability_recovery,
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
    bootstrap_codex_recovery,
    bootstrap_codex_timeline_projection,
)
from armi_cognition.api import (
    CognitionCandidateParser,
    CognitionContextLifecyclePort,
    CognitionExactLifeQueryPort,
    CognitionModelPort,
    CognitionOperationReadPort,
    CognitionRuntimeStatePort,
    CognitionWorkerPort,
)
from armi_cognition.bootstrap import (
    bootstrap_cognition_candidate,
    bootstrap_cognition_change_set_codec,
    bootstrap_cognition_exact_life_query,
    bootstrap_cognition_model,
    bootstrap_cognition_operation,
    bootstrap_cognition_recovery,
)
from armi_context.api import (
    EMBEDDING_DIMENSIONS,
    ContextCognitionReadPort,
    ContextEmbeddingRuntimePort,
    ContextProjectionInvalidationPort,
    ContextProjectionSourceRef,
    ContextRuntimePort,
    EmbeddingBinding,
)
from armi_context.bootstrap import (
    ContextCandidateReadPorts,
    bootstrap_context,
    bootstrap_context_candidate_read,
    bootstrap_context_embedding,
    bootstrap_context_projection_invalidation,
    bootstrap_context_recovery,
)
from armi_data_rights.api import (
    DataRightsCognitionGate,
    DataRightsEffectGate,
    DataRightsInteractionGate,
    DataRightsProjectionInvalidationPort,
    DataRightsSubjectCommitGate,
)
from armi_data_rights.bootstrap import (
    DataRightsCore,
    DataRightsModule,
    bootstrap_data_rights,
    bootstrap_data_rights_core,
    bootstrap_data_rights_recovery,
)
from armi_effect.api import (
    ActionAdapterPort,
    EffectCodexArtifactPort,
    EffectGrantCancellationPort,
    EffectOperationReadPort,
    EffectRegistrationContextPort,
    EffectRuntimePort,
    ResponseAdmissionRuntimePort,
)
from armi_effect.bootstrap import (
    bootstrap_effect_codex_lifecycle,
    bootstrap_effect_grant_cancellation,
    bootstrap_effect_operation_read,
    bootstrap_effect_recovery,
    bootstrap_effect_runtime,
    bootstrap_expression_effect_registration,
    bootstrap_response_admission,
)
from armi_evidence.api import EvidenceReadPort, EvidenceWritePort
from armi_evidence.bootstrap import (
    EvidenceModule,
    bootstrap_evidence,
    bootstrap_evidence_recovery,
)
from armi_expression.api import (
    ExpressionCommitPort,
    ExpressionEffectLinkPort,
    ExpressionIntentReadPort,
    ExpressionResponseAdmissionPort,
)
from armi_expression.bootstrap import (
    ExpressionModule,
    bootstrap_expression,
    bootstrap_expression_recovery,
)
from armi_interaction.api import (
    CreatorIdentityContext,
    CreatorInputTransactionPort,
    CreatorOperationQueryPort,
    InteractionCognitionReadPort,
    InteractionContextReadPort,
    InteractionEffectDeliveryPort,
    InteractionEffectRoutePort,
    InteractionIdentityPort,
    InteractionPerceptionPort,
    InteractionSceneTransitionPort,
)
from armi_interaction.bootstrap import (
    InteractionModule,
    bootstrap_interaction,
    bootstrap_interaction_cognition,
    bootstrap_interaction_identity,
    bootstrap_interaction_recovery,
)
from armi_kernel import load_yaml_file
from armi_kernel.application import (
    CreatorProjectionNotifier,
    CredentialPort,
    CredentialPurpose,
    LifeRecordQueryPort,
    ModelBinding,
    ModelViolation,
    RuntimeFence,
)
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
    bootstrap_material_recovery,
)
from armi_memory.api import (
    MemoryCandidateContextPort,
    MemoryCognitionPort,
    MemoryCommitPort,
    MemoryDataRightsParticipant,
    MemoryProjectionPort,
    MemoryReadPort,
)
from armi_memory.bootstrap import (
    MemoryModule,
    bootstrap_memory,
    bootstrap_memory_recovery,
)
from armi_mood.api import MoodCognitionPort, MoodCommitPort, MoodReadPort
from armi_mood.bootstrap import MoodModule, bootstrap_mood, bootstrap_mood_recovery
from armi_opportunity.api import (
    OpportunityAdmissionPort,
    OpportunityCognitionPort,
    OpportunityCognitionSelectionPort,
    OpportunityContextReadPort,
    OpportunityOperationReadPort,
    OpportunityRuntimePort,
)
from armi_opportunity.bootstrap import (
    bootstrap_opportunity,
    bootstrap_opportunity_admission,
    bootstrap_opportunity_operation,
    bootstrap_opportunity_recovery,
    bootstrap_opportunity_transition,
)
from armi_perception.api import ExternalMediaFetchPort
from armi_perception.bootstrap import (
    PerceptionModule,
    bootstrap_perception,
    bootstrap_perception_recovery,
)
from armi_prompt.api import (
    PromptCognitionPort,
    PromptCommitPort,
    PromptReadPort,
)
from armi_prompt.bootstrap import (
    PromptModule,
    bootstrap_prompt,
    bootstrap_prompt_recovery,
)
from armi_relationship.api import (
    RelationshipCognitionPort,
    RelationshipCommitPort,
    RelationshipDataRightsParticipant,
    RelationshipPolicyPort,
    RelationshipReadPort,
)
from armi_relationship.bootstrap import (
    RelationshipModule,
    bootstrap_relationship,
    bootstrap_relationship_recovery,
)
from armi_runtime_foundation import (
    PostgreSQLTransaction,
    RecoveryOwnerIdentity,
    RecoveryParticipant,
)
from armi_sleep.api import (
    SleepCognitionPort,
    SleepCommitPort,
    SleepMaintenancePort,
    SleepReadPort,
)
from armi_sleep.bootstrap import SleepModule, bootstrap_sleep, bootstrap_sleep_recovery
from armi_subject_state.api import (
    SubjectStateCognitionPort,
    SubjectStateCommitPort,
    SubjectStateReadPort,
)
from armi_subject_state.bootstrap import (
    SubjectStateModule,
    bootstrap_subject_state,
    bootstrap_subject_state_recovery,
    probe_subject_state_counts,
)
from armi_web_observation.api import (
    WebContextReadPort,
    WebObservationRuntimePort,
    WebObservationViolation,
    WebResearchRuntimePort,
)
from armi_web_observation.bootstrap import (
    bootstrap_web_observation,
    bootstrap_web_observation_recovery,
    bootstrap_web_research,
    bootstrap_web_research_commit,
)

from armi_runtime.adapters.model.doubao_speech import DoubaoSpeechRecognizer
from armi_runtime.adapters.model.external_content import (
    VolcengineArkExternalContentRecognizer,
    load_external_recognition_binding,
)
from armi_runtime.adapters.model.volcengine_ark import (
    CandidateParser,
    VolcengineArkModelAdapter,
)
from armi_runtime.adapters.model.volcengine_embedding import (
    VolcengineArkEmbeddingAdapter,
)
from armi_runtime.adapters.persistence.birth import (
    ContinuityState,
    probe_continuity,
)
from armi_runtime.adapters.persistence.durable_work import PostgreSQLDurableWorkGateway
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
    RuntimeCodexGrantActivation,
    RuntimeEffectRegistrationContext,
)
from armi_runtime.application.cognition_cycle import (
    RuntimeCognitionCycleSelector,
    RuntimeCognitionState,
    RuntimeContextEpisodeAdapter,
)
from armi_runtime.application.operation_assembler import (
    RuntimeCreatorOperationAssembler,
)

from .birth_manifest import packaged_birth_digests
from .config_assets import runtime_config_path
from .configuration import ConfigurationViolation
from .environment import PreparedEnvironment
from .exact_life_query_pipeline import (
    ExactLifeQueryPipeline,
    build_exact_life_query_pipeline,
)
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

_EMBEDDING_BINDING_ID: Final = "armi.embedding.volcengine-ark-doubao-vision-250615-v1"
_EMBEDDING_MODEL_ID: Final = "doubao-embedding-vision-250615"

_REASON_BY_CODE: Final = {
    "DB-CONNECTION-UNAVAILABLE": "RUNTIME_DATABASE_UNAVAILABLE",
    "DB-PG-VERSION": "RUNTIME_DATABASE_VERSION_MISMATCH",
    "DB-PGVECTOR-IDENTITY": "RUNTIME_DATABASE_IDENTITY_MISMATCH",
    "DB-DATABASE-IDENTITY": "RUNTIME_DATABASE_IDENTITY_MISMATCH",
    "DB-RUNTIME-ROLE-UNSAFE": "RUNTIME_DATABASE_ROLE_UNSAFE",
    "DB-SCHEMA-MISSING": "RUNTIME_SCHEMA_MISSING",
    "DB-SCHEMA-EXISTS": "RUNTIME_SCHEMA_INVALID",
    "DB-SCHEMA-HISTORY": "RUNTIME_SCHEMA_INVALID",
    "DB-SCHEMA-INVARIANT": "RUNTIME_SCHEMA_INVALID",
    "DB-SCHEMA-PENDING": "RUNTIME_SCHEMA_MIGRATION_REQUIRED",
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


def _load_embedding_binding() -> EmbeddingBinding:
    try:
        value = cast(
            dict[str, Any],
            load_yaml_file(runtime_config_path("model-bindings.yaml"))["embedding"],
        )
    except OSError, KeyError, TypeError, ValueError:
        raise ModelViolation("MODEL-BINDING-MANIFEST") from None
    expected = {
        "provider": "volcengine_ark",
        "api_base": "https://ark.cn-beijing.volces.com/api/v3",
        "model_id": _EMBEDDING_MODEL_ID,
        "model_binding": _EMBEDDING_BINDING_ID,
        "version_policy": "fixed_model_id",
        "dimensions": EMBEDDING_DIMENSIONS,
        "timeout_seconds": 60,
        "credential_identity": "armi.model.ark-api-key.v1",
        "credential_locator": "model.ark_api_key",
        "credential_purpose": "model.embedding",
    }
    if value != expected:
        raise ModelViolation("MODEL-BINDING-MANIFEST")
    return EmbeddingBinding(
        provider=value["provider"],
        api_base=value["api_base"],
        model_id=value["model_id"],
        model_binding=value["model_binding"],
        dimensions=value["dimensions"],
        timeout_seconds=value["timeout_seconds"],
        credential_identity=value["credential_identity"],
        credential_locator=value["credential_locator"],
        credential_purpose=value["credential_purpose"],
    )


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
                if operation == "migrate":
                    return gateway.migrate(
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


def install_operator_schema(prepared: PreparedEnvironment) -> SchemaStatus:
    return _with_connection(
        prepared,
        locator_name=MIGRATOR_LOCATOR_NAME,
        purpose="database.migrator",
        operation="install",
    )


def migrate_operator_schema(prepared: PreparedEnvironment) -> SchemaStatus:
    return _with_connection(
        prepared,
        locator_name=MIGRATOR_LOCATOR_NAME,
        purpose="database.migrate",
        operation="migrate",
    )


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
                )
                if state is ContinuityState.BORN:
                    heads, revisions = probe_subject_state_counts(conninfo)
                    if heads != 3 or revisions < 3:
                        return ContinuityState.INVALID
                return state

            return handle.consume(invoke)
    except ConfigurationViolation:
        return ContinuityState.INVALID


def compose_runtime_observation(
    unit_of_work_factory: PostgreSQLUnitOfWorkFactory,
) -> PostgreSQLRuntimeObservation:
    """Resolve the Runtime credential for the private read-only sampler."""

    return PostgreSQLRuntimeObservation(unit_of_work_factory)


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


async def inspect_creator_party_id(
    unit_of_work_factory: PostgreSQLUnitOfWorkFactory,
    *,
    subject_id: UUID,
    identity: InteractionIdentityPort,
) -> UUID | None:
    context = await inspect_creator_context(
        unit_of_work_factory,
        subject_id=subject_id,
        identity=identity,
    )
    return None if context is None else context.party_id


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
    capability: CapabilityOperationReadPort,
    codex: CodexTaskSourceReadPort,
    codex_executions: CodexExecutionReadPort,
) -> CreatorOperationQueryPort:
    opportunity: OpportunityOperationReadPort = bootstrap_opportunity_operation()
    cognition: CognitionOperationReadPort = bootstrap_cognition_operation()
    effect: EffectOperationReadPort = bootstrap_effect_operation_read()
    return RuntimeCreatorOperationAssembler(
        factory=unit_of_work_factory,
        creator_party_id=creator_party_id,
        opportunity=opportunity,
        cognition=cognition,
        interaction=interaction,
        evidence=evidence,
        expression=expression,
        capability=capability,
        effect=effect,
        codex=codex,
        codex_executions=codex_executions,
    )


def compose_interaction_module(
    prepared: PreparedEnvironment,
    *,
    unit_of_work_factory: PostgreSQLUnitOfWorkFactory,
    creator_party_id: UUID,
    cursor_key: bytes,
    notifier: CreatorProjectionNotifier | None,
    subject_state_read: SubjectStateReadPort,
    evidence: EvidenceWritePort,
    evidence_read: EvidenceReadPort,
    opportunity: OpportunityAdmissionPort,
    data_rights: DataRightsInteractionGate,
    identity: InteractionIdentityPort,
    wakeups: WorkWakeupBus | None = None,
    diagnostic: Callable[[str], None] | None = None,
    fault_injector: Callable[[str], None] | None = None,
) -> InteractionModule:
    """Resolve and bind the one active interaction owner implementation."""

    config = prepared.effective.config
    return bootstrap_interaction(
        unit_of_work_factory,
        environment_id=config.environment.environment_id,
        creator_party_id=creator_party_id,
        cursor_key=cursor_key,
        storage=ContentAddressedArtifactStore(
            prepared.data_root / "artifacts",
            max_object_bytes=config.artifacts.max_object_bytes,
        ),
        codex_task_projection=bootstrap_codex_timeline_projection(),
        catalog=bootstrap_artifact_catalog(),
        data_rights=data_rights,
        identity=identity,
        subject_state=subject_state_read,
        evidence=evidence,
        evidence_read=evidence_read,
        opportunity=opportunity,
        notifier=notifier,
        wakeups=wakeups,
        diagnostic=diagnostic,
        fault_injector=fault_injector,
    )


def compose_activity_module(
    unit_of_work_factory: PostgreSQLUnitOfWorkFactory,
    *,
    creator_party_id: UUID,
    subject_state: SubjectStateReadPort,
) -> ActivityModule:
    """Resolve and bind the one active Activity owner implementation."""

    return bootstrap_activity(
        unit_of_work_factory,
        creator_party_id=creator_party_id,
        focus=subject_state,
    )


def compose_subject_state_module() -> SubjectStateModule:
    """Bind the sole active Self, Mind, and life-mode owner."""

    return bootstrap_subject_state()


def compose_mood_module() -> MoodModule:
    """Build the one active in-process mood owner."""

    return bootstrap_mood()


def compose_life_record_query(
    unit_of_work_factory: PostgreSQLUnitOfWorkFactory,
    *,
    environment_id: UUID,
    creator_party_id: UUID,
    cursor_key: bytes,
    activity_read: ActivityReadPort,
    memory_read: MemoryReadPort,
    material_read: MaterialReadPort,
    relationship_read: RelationshipReadPort,
    subject_state_read: SubjectStateReadPort,
) -> PostgreSQLLifeRecordQuery:
    """Resolve the shared read-only exact-life and memory projection."""

    return PostgreSQLLifeRecordQuery(
        unit_of_work_factory,
        environment_id=environment_id,
        creator_party_id=creator_party_id,
        cursor_key=cursor_key,
        activities=activity_read,
        materials=material_read,
        memories=memory_read,
        relationships=relationship_read,
        subject_state=subject_state_read,
    )


def compose_material_module(
    unit_of_work_factory: PostgreSQLUnitOfWorkFactory,
    *,
    subject_id: UUID,
    data_root: Path,
    max_object_bytes: int,
) -> MaterialModule:
    """Resolve and bind the one active life-material owner implementation."""

    return bootstrap_material(
        unit_of_work_factory,
        catalog=bootstrap_artifact_catalog(),
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
) -> PostgreSQLOtherHumanRecordQuery:
    """Resolve the read-only Creator record projection for other humans."""

    return PostgreSQLOtherHumanRecordQuery(
        unit_of_work_factory,
        environment_id=environment_id,
        cursor_key=cursor_key,
        data_root=data_root,
        max_object_bytes=max_object_bytes,
    )


def compose_exact_life_query_pipeline(
    prepared: PreparedEnvironment,
    *,
    unit_of_work_factory: PostgreSQLUnitOfWorkFactory,
    query: LifeRecordQueryPort,
    cognition: CognitionExactLifeQueryPort,
    opportunity: OpportunityAdmissionPort,
    wakeups: WorkWakeupBus | None = None,
    diagnostic: Callable[[str], None] | None = None,
) -> ExactLifeQueryPipeline:
    config = prepared.effective.config
    return build_exact_life_query_pipeline(
        unit_of_work_factory,
        data_root=prepared.data_root,
        max_object_bytes=config.artifacts.max_object_bytes,
        query=query,
        cognition=cognition,
        opportunity=opportunity,
        wakeups=wakeups,
        diagnostic=diagnostic,
    )


def compose_cognition_exact_life_query() -> CognitionExactLifeQueryPort:
    return bootstrap_cognition_exact_life_query()


def compose_relationship_module(
    unit_of_work_factory: PostgreSQLUnitOfWorkFactory,
    *,
    creator_party_id: UUID,
) -> RelationshipModule:
    """Resolve and bind the one active relationship owner implementation."""

    return bootstrap_relationship(
        unit_of_work_factory,
        creator_party_id=creator_party_id,
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
) -> MemoryModule:
    """Resolve and bind the one active subjective-memory owner implementation."""

    return bootstrap_memory(
        unit_of_work_factory,
        environment_id=environment_id,
        creator_party_id=creator_party_id,
        subject_id=subject_id,
        cursor_key=cursor_key,
    )


def compose_sleep_module(
    unit_of_work_factory: PostgreSQLUnitOfWorkFactory,
    *,
    creator_party_id: UUID,
) -> SleepModule:
    """Resolve and bind the one active sleep owner implementation."""

    return bootstrap_sleep(
        unit_of_work_factory,
        creator_party_id=creator_party_id,
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
    opportunity: OpportunityAdmissionPort,
    wakeups: WorkWakeupBus,
    diagnostic: Callable[[str], None] | None = None,
) -> PerceptionModule:
    model_locator = prepared.effective.config.secret_locators.get(MODEL_LOCATOR_NAME)
    speech_locator = prepared.effective.config.secret_locators.get(SPEECH_LOCATOR_NAME)
    if model_locator is None or speech_locator is None:
        raise ModelViolation("MODEL-CREDENTIAL")
    try:
        recognition_binding = load_external_recognition_binding(
            runtime_config_path("model-bindings.yaml")
        )
        config = prepared.effective.config
        return bootstrap_perception(
            unit_of_work_factory=unit_of_work_factory,
            storage=ContentAddressedArtifactStore(
                prepared.data_root / "artifacts",
                max_object_bytes=config.artifacts.max_object_bytes,
            ),
            catalog=bootstrap_artifact_catalog(),
            work=PostgreSQLDurableWorkGateway(unit_of_work_factory),
            evidence=evidence,
            evidence_read=evidence_read,
            interaction=interaction,
            opportunity=opportunity,
            fetch=fetch,
            ark_recognizer=VolcengineArkExternalContentRecognizer(
                credential_port=prepared.credential_port,
                locator=model_locator,
                binding=recognition_binding.ark,
            ),
            speech_recognizer=DoubaoSpeechRecognizer(
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
    creator_party_id: UUID,
) -> PromptModule:
    """Resolve the Runtime credential for the T-04 Creator Prompt owner."""

    config = prepared.effective.config
    catalog = bootstrap_artifact_catalog()
    return bootstrap_prompt(
        creator_party_id=creator_party_id,
        storage=ContentAddressedArtifactStore(
            prepared.data_root / "artifacts",
            max_object_bytes=config.artifacts.max_object_bytes,
        ),
        catalog=catalog,
        unit_of_work_factory=unit_of_work_factory,
    )


class _DataRightsContextProjectionInvalidation(DataRightsProjectionInvalidationPort):
    def __init__(self, target: ContextProjectionInvalidationPort) -> None:
        self._target = target

    async def invalidate(
        self,
        transaction: PostgreSQLTransaction,
        *,
        source_kind: str,
        source_refs: tuple[UUID, ...],
    ) -> None:
        await self._target.invalidate(
            transaction,
            tuple(
                ContextProjectionSourceRef(source_kind, source_ref)
                for source_ref in source_refs
            ),
        )


class _DataRightsSubjectEpoch:
    async def advance(
        self,
        transaction: PostgreSQLTransaction,
    ) -> None:
        await transaction.execute(
            """
            UPDATE armi.subjects
            SET state_epoch = state_epoch + 1
            WHERE singleton_key = 1
            """
        )


def compose_interaction_identity() -> InteractionIdentityPort:
    return bootstrap_interaction_identity()


def compose_interaction_cognition_ports():
    return bootstrap_interaction_cognition()


def compose_data_rights_module(
    prepared: PreparedEnvironment,
    *,
    unit_of_work_factory: PostgreSQLUnitOfWorkFactory,
    creator_party_id: UUID,
    memory_data_rights: MemoryDataRightsParticipant,
    relationship_data_rights: RelationshipDataRightsParticipant,
    context_projections: ContextProjectionInvalidationPort,
    core: DataRightsCore,
    parties: InteractionIdentityPort,
    notifier: CreatorProjectionNotifier | None = None,
) -> DataRightsModule:
    config = prepared.effective.config
    return bootstrap_data_rights(
        creator_party_id=creator_party_id,
        data_root=prepared.data_root,
        unit_of_work_factory=unit_of_work_factory,
        storage=ContentAddressedArtifactStore(
            prepared.data_root / "artifacts",
            max_object_bytes=config.artifacts.max_object_bytes,
        ),
        memory=memory_data_rights,
        relationship=relationship_data_rights,
        context_projections=_DataRightsContextProjectionInvalidation(
            context_projections
        ),
        core=core,
        parties=parties,
        subject_epoch=_DataRightsSubjectEpoch(),
        catalog=bootstrap_artifact_catalog(),
        notifier=notifier,
    )


def compose_data_rights_core() -> DataRightsCore:
    return bootstrap_data_rights_core()


def compose_context_projection_invalidation() -> ContextProjectionInvalidationPort:
    return bootstrap_context_projection_invalidation()


def compose_context_candidate_read() -> ContextCandidateReadPorts:
    return bootstrap_context_candidate_read()


def compose_life_opportunity_pipeline(
    prepared: PreparedEnvironment,
    *,
    unit_of_work_factory: PostgreSQLUnitOfWorkFactory,
    activity_read: ActivityReadPort,
    relationship_read: RelationshipReadPort,
    relationship_policy: RelationshipPolicyPort,
    sleep_maintenance: SleepMaintenancePort,
    sleep_read: SleepReadPort,
    material_read: MaterialReadPort,
    subject_state_read: SubjectStateReadPort,
    wakeups: WorkWakeupBus | None = None,
    notifier: CreatorProjectionNotifier | None = None,
) -> OpportunityRuntimePort:
    """Resolve the Runtime credential for the P0-S001 source owner."""

    config = prepared.effective.config
    return bootstrap_opportunity(
        factory=unit_of_work_factory,
        activity_read=activity_read,
        relationship_read=relationship_read,
        relationship_policy=relationship_policy,
        sleep_maintenance=sleep_maintenance,
        sleep_read=sleep_read,
        material_read=material_read,
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
    interaction_cognition: InteractionCognitionReadPort,
    opportunity_cognition: OpportunityCognitionPort,
    runtime_subjects: RuntimeCognitionState,
    web_context: WebContextReadPort,
    expression_read: ExpressionIntentReadPort,
    effect_read: EffectOperationReadPort,
    data_rights: DataRightsCognitionGate,
    memory_read: MemoryReadPort,
    memory_projection: MemoryProjectionPort,
    mood_read: MoodReadPort,
    prompt_read: PromptReadPort,
    material_projection: MaterialProjectionPort,
    relationship_read: RelationshipReadPort,
    sleep_read: SleepReadPort,
    subject_state_read: SubjectStateReadPort,
    wakeups: WorkWakeupBus | None = None,
    diagnostic: Callable[[str], None] | None = None,
) -> ContextRuntimePort:
    """Resolve the Runtime credential for the active S023 selector and worker."""

    embedding_locator = (
        prepared.effective.config.secret_locators.get(MODEL_LOCATOR_NAME)
        if prepared.effective.config.model.semantic_recall_enabled
        else None
    )
    config = prepared.effective.config
    selection = RuntimeCognitionCycleSelector(
        factory=unit_of_work_factory,
        opportunities=opportunity_cognition,
        episodes=cognition_context,
        sleep=sleep_read,
        data_rights=data_rights,
        evidence=evidence_read,
        interaction=interaction_cognition,
        web=web_context,
        codex_context=codex_context,
        codex_sources=codex_read,
        effects=effect_read,
        expression=expression_read,
    )
    return bootstrap_context(
        factory=unit_of_work_factory,
        storage=ContentAddressedArtifactStore(
            prepared.data_root / "artifacts",
            max_object_bytes=config.artifacts.max_object_bytes,
        ),
        catalog=bootstrap_artifact_catalog(),
        work=PostgreSQLDurableWorkGateway(unit_of_work_factory),
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
        selection=selection,
        episodes=RuntimeContextEpisodeAdapter(cognition_context),
        runtime_subjects=runtime_subjects,
        opportunity_context=opportunity_cognition,
        opportunity_transitions=opportunity_cognition,
        evidence_read=evidence_read,
        interaction_context=interaction_context,
        expression_read=expression_read,
        effect_read=effect_read,
        codex_read=codex_read,
        web_search_active=config.web.enabled,
        wakeups=wakeups,
        diagnostic=diagnostic,
        embedding=(
            VolcengineArkEmbeddingAdapter(
                binding=_load_embedding_binding(),
                credential_port=prepared.credential_port,
                locator=embedding_locator,
            )
            if embedding_locator is not None
            else None
        ),
    )


def compose_context_embedding_pipeline(
    prepared: PreparedEnvironment,
    *,
    unit_of_work_factory: PostgreSQLUnitOfWorkFactory,
    memory_projection: MemoryProjectionPort,
    material_projection: MaterialProjectionPort,
) -> ContextEmbeddingRuntimePort:
    embedding_locator = prepared.effective.config.secret_locators.get(
        MODEL_LOCATOR_NAME
    )
    if embedding_locator is None:
        raise ModelViolation("MODEL-CREDENTIAL")
    config = prepared.effective.config
    return bootstrap_context_embedding(
        factory=unit_of_work_factory,
        storage=ContentAddressedArtifactStore(
            prepared.data_root / "artifacts",
            max_object_bytes=config.artifacts.max_object_bytes,
        ),
        adapter=VolcengineArkEmbeddingAdapter(
            binding=_load_embedding_binding(),
            credential_port=prepared.credential_port,
            locator=embedding_locator,
        ),
        work=PostgreSQLDurableWorkGateway(unit_of_work_factory),
        memories=memory_projection,
        materials=material_projection,
    )


def compose_model_pipeline(
    prepared: PreparedEnvironment,
    *,
    unit_of_work_factory: PostgreSQLUnitOfWorkFactory,
    context: ContextCognitionReadPort,
    opportunities: OpportunityCognitionSelectionPort,
    wakeups: WorkWakeupBus | None = None,
    diagnostic: Callable[[str], None] | None = None,
) -> CognitionWorkerPort:
    """Resolve the Runtime and model credentials for the active S024 worker."""

    model_locator = prepared.effective.config.secret_locators.get(MODEL_LOCATOR_NAME)
    if model_locator is None:
        raise ModelViolation("MODEL-CREDENTIAL")
    config = prepared.effective.config

    def adapter_factory(
        *,
        binding: ModelBinding,
        candidate_schema: dict[str, Any],
        candidate_parser: CognitionCandidateParser,
        instructions: str | None = None,
        schema_name: str | None = None,
    ) -> CognitionModelPort:
        parser = cast(CandidateParser, candidate_parser)
        if instructions is None and schema_name is None:
            return VolcengineArkModelAdapter(
                binding=binding,
                credential_port=prepared.credential_port,
                locator=model_locator,
                candidate_schema=candidate_schema,
                candidate_parser=parser,
            )
        if instructions is None or schema_name is None:
            raise ModelViolation("MODEL-BINDING")
        return VolcengineArkModelAdapter(
            binding=binding,
            credential_port=prepared.credential_port,
            locator=model_locator,
            candidate_schema=candidate_schema,
            candidate_parser=parser,
            instructions=instructions,
            schema_name=schema_name,
        )

    return bootstrap_cognition_model(
        factory=unit_of_work_factory,
        storage=ContentAddressedArtifactStore(
            prepared.data_root / "artifacts",
            max_object_bytes=config.artifacts.max_object_bytes,
        ),
        catalog=bootstrap_artifact_catalog(),
        context=context,
        opportunities=opportunities,
        work=PostgreSQLDurableWorkGateway(unit_of_work_factory),
        adapter_factory=adapter_factory,
        binding_path=runtime_config_path("model-bindings.yaml"),
        web_search_active=config.web.enabled,
        wakeups=wakeups,
        diagnostic=diagnostic,
    )


def compose_web_search_pipeline(
    prepared: PreparedEnvironment,
    *,
    unit_of_work_factory: PostgreSQLUnitOfWorkFactory,
    evidence: EvidenceWritePort,
    opportunity: OpportunityAdmissionPort,
    diagnostic: Callable[[str], None] | None = None,
) -> WebObservationRuntimePort:
    """Resolve the fixed database and Ark credentials for S033 custody."""

    model_locator = prepared.effective.config.secret_locators.get(MODEL_LOCATOR_NAME)
    if model_locator is None:
        raise WebObservationViolation("WEB-CREDENTIAL")
    try:
        manifest_bytes = runtime_config_path("web-search.yaml").read_bytes()
    except OSError:
        raise WebObservationViolation("WEB-MANIFEST") from None
    config = prepared.effective.config
    return bootstrap_web_observation(
        factory=unit_of_work_factory,
        storage=ContentAddressedArtifactStore(
            prepared.data_root / "artifacts",
            max_object_bytes=config.artifacts.max_object_bytes,
        ),
        catalog=bootstrap_artifact_catalog(),
        work=PostgreSQLDurableWorkGateway(unit_of_work_factory),
        credential_port=prepared.credential_port,
        credential_locator=model_locator,
        manifest_bytes=manifest_bytes,
        evidence=evidence,
        opportunity=opportunity,
        diagnostic=diagnostic,
    )


def compose_web_research_admission_pipeline(
    prepared: PreparedEnvironment,
    *,
    unit_of_work_factory: PostgreSQLUnitOfWorkFactory,
    custody: WebObservationRuntimePort,
    evidence: EvidenceWritePort,
    opportunity: OpportunityAdmissionPort,
    diagnostic: Callable[[str], None] | None = None,
) -> WebResearchRuntimePort:
    """Resolve the active S034 intent-to-custody worker."""

    config = prepared.effective.config
    return bootstrap_web_research(
        factory=unit_of_work_factory,
        storage=ContentAddressedArtifactStore(
            prepared.data_root / "artifacts",
            max_object_bytes=config.artifacts.max_object_bytes,
        ),
        work=PostgreSQLDurableWorkGateway(unit_of_work_factory),
        custody=custody,
        evidence=evidence,
        opportunity=opportunity,
        diagnostic=diagnostic,
    )


def compose_candidate_validation_pipeline(
    prepared: PreparedEnvironment,
    *,
    unit_of_work_factory: PostgreSQLUnitOfWorkFactory,
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
    subject_state_read: SubjectStateReadPort,
    wakeups: WorkWakeupBus | None = None,
    diagnostic: Callable[[str], None] | None = None,
) -> CognitionWorkerPort:
    """Resolve the Runtime credential for the active S025 validator."""

    config = prepared.effective.config
    return bootstrap_cognition_candidate(
        factory=unit_of_work_factory,
        storage=ContentAddressedArtifactStore(
            prepared.data_root / "artifacts",
            max_object_bytes=config.artifacts.max_object_bytes,
        ),
        catalog=bootstrap_artifact_catalog(),
        work=PostgreSQLDurableWorkGateway(unit_of_work_factory),
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
        subject_state_read=subject_state_read,
        web_search_active=config.web.enabled,
        wakeups=wakeups,
        diagnostic=diagnostic,
    )


def compose_subject_commit_pipeline(
    prepared: PreparedEnvironment,
    *,
    unit_of_work_factory: PostgreSQLUnitOfWorkFactory,
    activity_cognition: ActivityCognitionPort,
    activity_commit: ActivityCommitPort,
    capability_commit: CapabilityCommitPort,
    capability_read: CapabilityReadPort,
    codex_commit: CodexCommitPort,
    context_projections: ContextProjectionInvalidationPort,
    data_rights: DataRightsSubjectCommitGate,
    evidence: EvidenceWritePort,
    evidence_read: EvidenceReadPort,
    expression_commit: ExpressionCommitPort,
    memory_commit: MemoryCommitPort,
    memory_cognition: MemoryCognitionPort,
    mood_commit: MoodCommitPort,
    mood_cognition: MoodCognitionPort,
    prompt_cognition: PromptCognitionPort,
    prompt_commit: PromptCommitPort,
    material_cognition: MaterialCognitionPort,
    material_commit: MaterialCommitPort,
    relationship_cognition: RelationshipCognitionPort,
    relationship_commit: RelationshipCommitPort,
    sleep_cognition: SleepCognitionPort,
    sleep_commit: SleepCommitPort,
    subject_state_cognition: SubjectStateCognitionPort,
    subject_state_commit: SubjectStateCommitPort,
    notifier: CreatorProjectionNotifier | None,
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
        change_set_codec=bootstrap_cognition_change_set_codec(
            activity=activity_cognition,
            material=material_cognition,
            memory=memory_cognition,
            mood=mood_cognition,
            prompt=prompt_cognition,
            relationship=relationship_cognition,
            sleep=sleep_cognition,
            subject_state=subject_state_cognition,
        ),
        activity_cognition=activity_cognition,
        activity_commit=activity_commit,
        capability_commit=capability_commit,
        capability_read=capability_read,
        codex_commit=codex_commit,
        context_projections=context_projections,
        data_rights=data_rights,
        evidence=evidence,
        evidence_read=evidence_read,
        expression_commit=expression_commit,
        memory_commit=memory_commit,
        memory_cognition=memory_cognition,
        mood_commit=mood_commit,
        mood_cognition=mood_cognition,
        opportunity_transition=bootstrap_opportunity_transition(),
        prompt_cognition=prompt_cognition,
        prompt_commit=prompt_commit,
        material_cognition=material_cognition,
        material_commit=material_commit,
        relationship_cognition=relationship_cognition,
        relationship_commit=relationship_commit,
        sleep_cognition=sleep_cognition,
        sleep_commit=sleep_commit,
        subject_state_cognition=subject_state_cognition,
        subject_state_commit=subject_state_commit,
        web_research_commit=bootstrap_web_research_commit(),
        notifier=notifier,
        wakeups=wakeups,
        diagnostic=diagnostic,
        fault_injector=fault_injector,
    )


def compose_effect_grant_cancellation() -> EffectGrantCancellationPort:
    return bootstrap_effect_grant_cancellation()


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
    )


def compose_capability_policy(
    prepared: PreparedEnvironment,
    *,
    unit_of_work_factory: PostgreSQLUnitOfWorkFactory,
    cursor_key: bytes,
    effect_cancellation: EffectGrantCancellationPort,
    codex_activation: RuntimeCodexGrantActivation,
    notifier: CreatorProjectionNotifier | None = None,
) -> CapabilityModule:
    """Resolve the Runtime credential for the sole active T-04 policy."""

    return bootstrap_capability(
        unit_of_work_factory,
        environment_id=prepared.effective.config.environment.environment_id,
        cursor_key=cursor_key,
        effect_cancellation=effect_cancellation,
        codex_activation=codex_activation,
        notifier=notifier,
    )


def compose_response_admission_pipeline(
    prepared: PreparedEnvironment,
    *,
    unit_of_work_factory: PostgreSQLUnitOfWorkFactory,
    expression: ExpressionResponseAdmissionPort,
    capability: CapabilityAdmissionPort,
    data_rights: DataRightsEffectGate,
    wakeups: WorkWakeupBus,
    diagnostic: Callable[[str], None] | None = None,
) -> ResponseAdmissionRuntimePort:
    """Resolve the Runtime credential for the S028 admission worker."""

    config = prepared.effective.config
    return bootstrap_response_admission(
        factory=unit_of_work_factory,
        storage=ContentAddressedArtifactStore(
            prepared.data_root / "artifacts",
            max_object_bytes=config.artifacts.max_object_bytes,
        ),
        work=PostgreSQLDurableWorkGateway(unit_of_work_factory),
        artifacts=bootstrap_artifact_catalog(),
        capability=capability,
        data_rights=data_rights,
        expression=expression,
        wakeups=wakeups,
        diagnostic=diagnostic,
    )


def compose_recovery_participants(
    *,
    mood_read: MoodReadPort,
    prompt_read: PromptReadPort,
    subject_state_read: SubjectStateReadPort,
) -> tuple[tuple[RecoveryParticipant, ...], tuple[RecoveryOwnerIdentity, ...]]:
    """Construct the fixed owner roster without starting external adapters."""

    expected_owners = tuple(
        RecoveryOwnerIdentity(value)
        for value in (
            "subject-state",
            "mood",
            "prompt",
            "activity",
            "material",
            "memory",
            "relationship",
            "sleep",
            "context",
            "interaction",
            "perception",
            "evidence",
            "cognition",
            "opportunity",
            "expression",
            "capability",
            "effect",
            "web-observation",
            "codex",
            "data-rights",
        )
    )
    participants: tuple[RecoveryParticipant, ...] = (
        bootstrap_subject_state_recovery(subject_state_read),
        bootstrap_mood_recovery(mood_read),
        bootstrap_prompt_recovery(prompt_read),
        bootstrap_activity_recovery(),
        bootstrap_material_recovery(),
        bootstrap_memory_recovery(),
        bootstrap_relationship_recovery(),
        bootstrap_sleep_recovery(),
        bootstrap_context_recovery(),
        bootstrap_interaction_recovery(),
        bootstrap_perception_recovery(),
        bootstrap_evidence_recovery(),
        bootstrap_cognition_recovery(),
        bootstrap_opportunity_recovery(),
        bootstrap_expression_recovery(),
        bootstrap_capability_recovery(),
        bootstrap_effect_recovery(),
        bootstrap_web_observation_recovery(),
        bootstrap_codex_recovery(),
        bootstrap_data_rights_recovery(),
    )
    return participants, expected_owners


def compose_runtime_recovery(
    prepared: PreparedEnvironment,
    *,
    unit_of_work_factory: PostgreSQLUnitOfWorkFactory,
    authority_admission: Callable[[], RuntimeFence],
    mood_read: MoodReadPort,
    prompt_read: PromptReadPort,
    subject_state_read: SubjectStateReadPort,
) -> PostgreSQLRuntimeRecovery:
    """Resolve the Runtime credential for the fenced startup recovery gateway."""

    config = prepared.effective.config
    participants, expected_owners = compose_recovery_participants(
        mood_read=mood_read,
        prompt_read=prompt_read,
        subject_state_read=subject_state_read,
    )
    return PostgreSQLRuntimeRecovery(
        unit_of_work_factory,
        environment_id=config.environment.environment_id,
        data_root=prepared.data_root,
        max_object_bytes=config.artifacts.max_object_bytes,
        authority_admission=authority_admission,
        participants=participants,
        expected_owners=expected_owners,
        catalog=bootstrap_artifact_catalog(),
    )


def compose_effect_registration_pipeline(
    prepared: PreparedEnvironment,
    *,
    unit_of_work_factory: PostgreSQLUnitOfWorkFactory,
    authorization: CapabilityActionAuthorizationPort,
    intents: ExpressionIntentReadPort,
    effect_links: ExpressionEffectLinkPort,
    registration_context: EffectRegistrationContextPort,
    codex_artifacts: EffectCodexArtifactPort,
    routes: InteractionEffectRoutePort,
    interaction_delivery: InteractionEffectDeliveryPort,
    notifier: CreatorProjectionNotifier | None = None,
    wakeups: WorkWakeupBus,
    diagnostic: Callable[[str], None] | None = None,
    fault_injector: Callable[[str], None] | None = None,
    external_message_adapter: ActionAdapterPort | None = None,
) -> EffectRuntimePort:
    """Resolve the Runtime credential for the S029 T-05 worker."""

    config = prepared.effective.config
    return bootstrap_effect_runtime(
        factory=unit_of_work_factory,
        storage=ContentAddressedArtifactStore(
            prepared.data_root / "artifacts",
            max_object_bytes=config.artifacts.max_object_bytes,
        ),
        work=PostgreSQLDurableWorkGateway(unit_of_work_factory),
        authorization=authorization,
        intents=intents,
        effect_links=effect_links,
        registration_context=registration_context,
        codex_artifacts=codex_artifacts,
        routes=routes,
        interaction_delivery=interaction_delivery,
        notifier=notifier,
        wakeups=wakeups,
        diagnostic=diagnostic,
        fault_injector=fault_injector,
        external_message_adapter=external_message_adapter,
    )


def compose_codex_read_ports() -> CodexReadPorts:
    return bootstrap_codex_read_ports()


def compose_effect_owner_context(
    *,
    expression: ExpressionIntentReadPort,
    interaction: InteractionEffectRoutePort,
    codex: CodexReadPorts,
) -> tuple[RuntimeEffectRegistrationContext, RuntimeCodexArtifactReference]:
    catalog = bootstrap_artifact_catalog()
    return (
        RuntimeEffectRegistrationContext(
            artifacts=catalog,
            codex=codex.task_sources,
            expression=expression,
            interaction=interaction,
        ),
        RuntimeCodexArtifactReference(
            artifacts=catalog,
            codex=codex.artifacts,
        ),
    )


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
    dispatch_authorization: CapabilityDispatchAuthorizationPort,
    expression: ExpressionIntentReadPort,
    sources: CodexTaskSourceReadPort,
    notifier: CreatorProjectionNotifier | None = None,
    diagnostic: Callable[[str], None] | None = None,
) -> CodexRuntimePort:
    """Compose the one active S039 Codex dispatcher without exposing auth."""

    auth_locator = prepared.effective.config.secret_locators.get(CODEX_LOCATOR_NAME)
    if auth_locator is None:
        raise CodexDelegationViolation("CODEX-DELEGATION-CREDENTIAL")
    config = prepared.effective.config
    run_root = prepared.data_root / "codex-runner"
    return bootstrap_codex(
        factory=unit_of_work_factory,
        storage=ContentAddressedArtifactStore(
            prepared.data_root / "artifacts",
            max_object_bytes=config.artifacts.max_object_bytes,
        ),
        catalog=bootstrap_artifact_catalog(),
        environment_root=prepared.root,
        run_root=run_root,
        creator_party_id=creator_party_id,
        creator_input=creator_input,
        evidence=evidence,
        evidence_read=evidence_read,
        identity=identity,
        opportunity=opportunity,
        effect=bootstrap_effect_codex_lifecycle(dispatch_authorization),
        expression=expression,
        sources=sources,
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
    "compose_capability_policy",
    "compose_codex_pipeline",
    "compose_codex_read_ports",
    "compose_cognition_exact_life_query",
    "compose_context_pipeline",
    "compose_creator_operation_query",
    "compose_data_rights_core",
    "compose_data_rights_module",
    "compose_effect_grant_cancellation",
    "compose_effect_owner_context",
    "compose_effect_registration_pipeline",
    "compose_evidence_module",
    "compose_exact_life_query_pipeline",
    "compose_expression_module",
    "compose_interaction_cognition_ports",
    "compose_interaction_identity",
    "compose_interaction_module",
    "compose_life_opportunity_pipeline",
    "compose_life_record_query",
    "compose_material_module",
    "compose_memory_module",
    "compose_model_pipeline",
    "compose_mood_module",
    "compose_opportunity_admission",
    "compose_other_human_record_query",
    "compose_perception_module",
    "compose_prompt_module",
    "compose_recovery_participants",
    "compose_relationship_module",
    "compose_response_admission_pipeline",
    "compose_runtime_authority",
    "compose_runtime_observation",
    "compose_runtime_recovery",
    "compose_runtime_unit_of_work_factory",
    "compose_sleep_module",
    "compose_subject_commit_pipeline",
    "compose_subject_state_module",
    "compose_web_research_admission_pipeline",
    "compose_web_search_pipeline",
    "inspect_creator_context",
    "inspect_creator_party_id",
    "inspect_operator_schema",
    "inspect_runtime_continuity",
    "inspect_runtime_schema",
    "install_operator_schema",
    "migrate_operator_schema",
    "runtime_database_reason",
)
