"""Explicit database composition for schema status, baseline, and migration."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Final, cast
from uuid import UUID

from armi_activity.api import (
    ActivityCognitionPort,
    ActivityCommitPort,
    ActivityReadPort,
    ActivityViolation,
)
from armi_activity.bootstrap import ActivityModule, bootstrap_activity
from armi_artifact_store.content_store import ContentAddressedArtifactStore
from armi_capability.api import (
    CapabilityCommitPort,
    CapabilityGrantConsumptionPort,
    CapabilityReadPort,
    CapabilityViolation,
)
from armi_capability.bootstrap import CapabilityModule, bootstrap_capability
from armi_codex.api import CodexDelegationViolation, CodexRuntimePort
from armi_codex.bootstrap import (
    bootstrap_codex,
    bootstrap_codex_commit,
)
from armi_cognition.api import (
    CognitionCandidateParser,
    CognitionModelPort,
    CognitionWorkerPort,
)
from armi_cognition.bootstrap import (
    bootstrap_cognition_candidate,
    bootstrap_cognition_model,
)
from armi_context import load_embedding_binding
from armi_context.api import ContextEmbeddingRuntimePort, ContextRuntimePort
from armi_context.bootstrap import bootstrap_context, bootstrap_context_embedding
from armi_data_rights.api import (
    DataRightsInteractionGate,
    DataRightsViolation,
)
from armi_data_rights.bootstrap import DataRightsModule, bootstrap_data_rights
from armi_effect.api import (
    ActionAdapterPort,
    EffectGrantCancellationPort,
    EffectRuntimePort,
    EffectViolation,
    ResponseAdmissionRuntimePort,
)
from armi_effect.bootstrap import (
    bootstrap_effect_dispatch_boundary,
    bootstrap_effect_grant_cancellation,
    bootstrap_effect_runtime,
    bootstrap_expression_effect_registration,
    bootstrap_response_admission,
)
from armi_evidence.api import EvidenceWritePort
from armi_evidence.bootstrap import EvidenceModule, bootstrap_evidence
from armi_expression.api import ResponseViolation
from armi_expression.bootstrap import bootstrap_expression
from armi_interaction.api import CreatorInputTransactionPort
from armi_interaction.bootstrap import InteractionModule, bootstrap_interaction
from armi_kernel.application import (
    CandidateViolation,
    CreatorProjectionNotifier,
    CredentialPort,
    CredentialPurpose,
    LifeRecordQueryPort,
    LifeRecordQueryViolation,
    ModelBinding,
    ModelViolation,
    OtherHumanRecordViolation,
    RuntimeFence,
    SubjectCommitViolation,
)
from armi_material.api import (
    MaterialCognitionPort,
    MaterialCommitPort,
    MaterialProjectionPort,
    MaterialReadPort,
    MaterialViolation,
)
from armi_material.bootstrap import MaterialModule, bootstrap_material
from armi_memory.api import (
    MemoryCognitionPort,
    MemoryCommitPort,
    MemoryDataRightsParticipant,
    MemoryProjectionPort,
    MemoryReadPort,
    MemoryViolation,
)
from armi_memory.bootstrap import MemoryModule, bootstrap_memory
from armi_mood.api import MoodCognitionPort, MoodCommitPort, MoodReadPort
from armi_mood.bootstrap import MoodModule, bootstrap_mood
from armi_opportunity.api import LifeViolation, OpportunityRuntimePort
from armi_opportunity.bootstrap import bootstrap_opportunity
from armi_perception.api import ExternalMediaFetchPort
from armi_perception.bootstrap import PerceptionModule, bootstrap_perception
from armi_prompt.api import (
    CreatorPromptViolation,
    PromptCognitionPort,
    PromptCommitPort,
    PromptReadPort,
)
from armi_prompt.bootstrap import PromptModule, bootstrap_prompt
from armi_relationship.api import (
    RelationshipCognitionPort,
    RelationshipCommitPort,
    RelationshipDataRightsParticipant,
    RelationshipPolicyPort,
    RelationshipReadPort,
    RelationshipViolation,
)
from armi_relationship.bootstrap import RelationshipModule, bootstrap_relationship
from armi_sleep.api import (
    CreatorMaintenanceViolation,
    SleepCognitionPort,
    SleepCommitPort,
    SleepMaintenancePort,
    SleepReadPort,
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
    probe_subject_state_counts,
)
from armi_web_observation.api import (
    WebObservationRuntimePort,
    WebObservationViolation,
    WebResearchRuntimePort,
    WebResearchViolation,
)
from armi_web_observation.bootstrap import (
    bootstrap_web_observation,
    bootstrap_web_research,
    bootstrap_web_research_commit,
)

from armi_runtime.adapters.creator_identity import CreatorContext, read_creator_context
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
from armi_runtime.adapters.persistence.artifact_catalog import ArtifactCatalogRepository
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
from armi_runtime.adapters.persistence.role_policy import physical_role_name
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
    prepared: PreparedEnvironment,
) -> PostgreSQLRuntimeObservation:
    """Resolve the Runtime credential for the private read-only sampler."""

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

            def create(value: memoryview) -> PostgreSQLRuntimeObservation:
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
                return PostgreSQLRuntimeObservation(
                    conninfo,
                    environment_id=config.environment.environment_id,
                    acquire_timeout_seconds=(
                        config.database.pool_acquire_timeout_seconds
                    ),
                    statement_timeout_seconds=(
                        config.database.diagnostic_statement_timeout_seconds
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


def inspect_creator_context(prepared: PreparedEnvironment) -> CreatorContext | None:
    """Read the unique born Creator and default scene without session state."""

    locator = prepared.effective.config.secret_locators.get(RUNTIME_LOCATOR_NAME)
    if locator is None:
        return None
    try:
        with prepared.credential_port.resolve(
            locator,
            CredentialPurpose("database.runtime"),
        ) as handle:

            def invoke(value: memoryview) -> CreatorContext | None:
                try:
                    conninfo = bytes(value).decode("utf-8")
                except UnicodeDecodeError:
                    return None
                return read_creator_context(conninfo)

            return handle.consume(invoke)
    except ConfigurationViolation:
        return None


def inspect_creator_party_id(prepared: PreparedEnvironment) -> UUID | None:
    context = inspect_creator_context(prepared)
    return None if context is None else context.party_id


def compose_evidence_module() -> EvidenceModule:
    """Bind the one active accepted-evidence owner implementation."""

    return bootstrap_evidence()


def compose_interaction_module(
    prepared: PreparedEnvironment,
    *,
    creator_party_id: UUID,
    cursor_key: bytes,
    authority_admission: Callable[[], RuntimeFence],
    notifier: CreatorProjectionNotifier | None,
    subject_state_read: SubjectStateReadPort,
    evidence: EvidenceWritePort,
    data_rights: DataRightsInteractionGate,
    wakeups: WorkWakeupBus | None = None,
    diagnostic: Callable[[str], None] | None = None,
    fault_injector: Callable[[str], None] | None = None,
) -> InteractionModule:
    """Resolve and bind the one active interaction owner implementation."""

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

            def create(value: memoryview) -> InteractionModule:
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
                expected_role = physical_role_name(
                    config.environment.environment_id, "runtime"
                )
                return bootstrap_interaction(
                    conninfo,
                    environment_id=config.environment.environment_id,
                    expected_role=expected_role,
                    creator_party_id=creator_party_id,
                    cursor_key=cursor_key,
                    pool_timeout_seconds=config.database.pool_acquire_timeout_seconds,
                    unit_of_work_factory=PostgreSQLUnitOfWorkFactory(
                        conninfo,
                        environment_id=config.environment.environment_id,
                        pool_min=config.database.pool_min,
                        pool_max=config.database.pool_max,
                        acquire_timeout_seconds=(
                            config.database.pool_acquire_timeout_seconds
                        ),
                        statement_timeout_seconds=(
                            config.database.statement_timeout_seconds
                        ),
                        authority_admission=authority_admission,
                    ),
                    storage=ContentAddressedArtifactStore(
                        prepared.data_root / "artifacts",
                        max_object_bytes=config.artifacts.max_object_bytes,
                    ),
                    catalog=ArtifactCatalogRepository(),
                    data_rights=data_rights,
                    subject_state=subject_state_read,
                    evidence=evidence,
                    notifier=notifier,
                    wakeups=wakeups,
                    diagnostic=diagnostic,
                    fault_injector=fault_injector,
                )

            return handle.consume(create)
    except ConfigurationViolation:
        raise DatabaseViolation(
            "DB-ROLE-CREDENTIAL-SCOPE",
            "the configured PostgreSQL connection is unavailable",
            status="unavailable",
            exit_code=3,
        ) from None


def compose_activity_module(
    prepared: PreparedEnvironment,
    *,
    creator_party_id: UUID,
    subject_state: SubjectStateReadPort,
) -> ActivityModule:
    """Resolve and bind the one active Activity owner implementation."""

    locator = prepared.effective.config.secret_locators.get(RUNTIME_LOCATOR_NAME)
    if locator is None:
        raise ActivityViolation("ACTIVITY-QUERY-UNAVAILABLE")
    try:
        with prepared.credential_port.resolve(
            locator,
            CredentialPurpose("database.runtime"),
        ) as handle:

            def create(value: memoryview) -> ActivityModule:
                try:
                    conninfo = bytes(value).decode("utf-8")
                except UnicodeDecodeError:
                    raise ActivityViolation("ACTIVITY-QUERY-UNAVAILABLE") from None
                config = prepared.effective.config
                return bootstrap_activity(
                    conninfo,
                    expected_role=physical_role_name(
                        config.environment.environment_id, "runtime"
                    ),
                    creator_party_id=creator_party_id,
                    pool_timeout_seconds=config.database.pool_acquire_timeout_seconds,
                    focus=subject_state,
                )

            return handle.consume(create)
    except ConfigurationViolation:
        raise ActivityViolation("ACTIVITY-QUERY-UNAVAILABLE") from None


def compose_subject_state_module() -> SubjectStateModule:
    """Bind the sole active Self, Mind, and life-mode owner."""

    return bootstrap_subject_state()


def compose_mood_module() -> MoodModule:
    """Build the one active in-process mood owner."""

    return bootstrap_mood()


def compose_life_record_query(
    prepared: PreparedEnvironment,
    *,
    creator_party_id: UUID,
    cursor_key: bytes,
    activity_read: ActivityReadPort,
    memory_read: MemoryReadPort,
    material_read: MaterialReadPort,
    relationship_read: RelationshipReadPort,
    subject_state_read: SubjectStateReadPort,
) -> PostgreSQLLifeRecordQuery:
    """Resolve the shared read-only exact-life and memory projection."""

    locator = prepared.effective.config.secret_locators.get(RUNTIME_LOCATOR_NAME)
    if locator is None:
        raise LifeRecordQueryViolation("LIFE-QUERY-UNAVAILABLE")
    try:
        with prepared.credential_port.resolve(
            locator,
            CredentialPurpose("database.runtime"),
        ) as handle:

            def create(value: memoryview) -> PostgreSQLLifeRecordQuery:
                try:
                    conninfo = bytes(value).decode("utf-8")
                except UnicodeDecodeError:
                    raise LifeRecordQueryViolation("LIFE-QUERY-UNAVAILABLE") from None
                config = prepared.effective.config
                return PostgreSQLLifeRecordQuery(
                    conninfo,
                    environment_id=config.environment.environment_id,
                    creator_party_id=creator_party_id,
                    cursor_key=cursor_key,
                    pool_timeout_seconds=config.database.pool_acquire_timeout_seconds,
                    activities=activity_read,
                    materials=material_read,
                    memories=memory_read,
                    relationships=relationship_read,
                    subject_state=subject_state_read,
                )

            return handle.consume(create)
    except ConfigurationViolation:
        raise LifeRecordQueryViolation("LIFE-QUERY-UNAVAILABLE") from None


def compose_material_module(
    prepared: PreparedEnvironment,
    *,
    creator_party_id: UUID,
) -> MaterialModule:
    """Resolve and bind the one active life-material owner implementation."""

    locator = prepared.effective.config.secret_locators.get(RUNTIME_LOCATOR_NAME)
    if locator is None:
        raise MaterialViolation("MATERIAL-QUERY-UNAVAILABLE")
    try:
        with prepared.credential_port.resolve(
            locator,
            CredentialPurpose("database.runtime"),
        ) as handle:

            def create(value: memoryview) -> MaterialModule:
                try:
                    conninfo = bytes(value).decode("utf-8")
                except UnicodeDecodeError:
                    raise MaterialViolation("MATERIAL-QUERY-UNAVAILABLE") from None
                config = prepared.effective.config
                return bootstrap_material(
                    conninfo,
                    expected_role=physical_role_name(
                        config.environment.environment_id, "runtime"
                    ),
                    creator_party_id=creator_party_id,
                    data_root=prepared.data_root,
                    max_object_bytes=config.artifacts.max_object_bytes,
                    pool_timeout_seconds=config.database.pool_acquire_timeout_seconds,
                )

            return handle.consume(create)
    except ConfigurationViolation:
        raise MaterialViolation("MATERIAL-QUERY-UNAVAILABLE") from None


def compose_other_human_record_query(
    prepared: PreparedEnvironment,
    *,
    cursor_key: bytes,
) -> PostgreSQLOtherHumanRecordQuery:
    """Resolve the read-only Creator record projection for other humans."""

    locator = prepared.effective.config.secret_locators.get(RUNTIME_LOCATOR_NAME)
    if locator is None:
        raise OtherHumanRecordViolation("OTHER-HUMAN-RECORD-UNAVAILABLE")
    try:
        with prepared.credential_port.resolve(
            locator, CredentialPurpose("database.runtime")
        ) as handle:

            def create(value: memoryview) -> PostgreSQLOtherHumanRecordQuery:
                try:
                    conninfo = bytes(value).decode("utf-8")
                except UnicodeDecodeError:
                    raise OtherHumanRecordViolation(
                        "OTHER-HUMAN-RECORD-UNAVAILABLE"
                    ) from None
                config = prepared.effective.config
                return PostgreSQLOtherHumanRecordQuery(
                    conninfo,
                    environment_id=config.environment.environment_id,
                    cursor_key=cursor_key,
                    data_root=prepared.data_root,
                    max_object_bytes=config.artifacts.max_object_bytes,
                    pool_timeout_seconds=config.database.pool_acquire_timeout_seconds,
                )

            return handle.consume(create)
    except ConfigurationViolation:
        raise OtherHumanRecordViolation("OTHER-HUMAN-RECORD-UNAVAILABLE") from None


def compose_exact_life_query_pipeline(
    prepared: PreparedEnvironment,
    *,
    authority_admission: Callable[[], RuntimeFence],
    query: LifeRecordQueryPort,
    wakeups: WorkWakeupBus | None = None,
    diagnostic: Callable[[str], None] | None = None,
) -> ExactLifeQueryPipeline:
    database_locator = prepared.effective.config.secret_locators.get(
        RUNTIME_LOCATOR_NAME
    )
    if database_locator is None:
        raise LifeRecordQueryViolation("LIFE-QUERY-UNAVAILABLE")
    try:
        with prepared.credential_port.resolve(
            database_locator,
            CredentialPurpose("database.runtime"),
        ) as handle:

            def create(value: memoryview) -> ExactLifeQueryPipeline:
                try:
                    conninfo = bytes(value).decode("utf-8")
                except UnicodeDecodeError:
                    raise LifeRecordQueryViolation("LIFE-QUERY-UNAVAILABLE") from None
                config = prepared.effective.config
                return build_exact_life_query_pipeline(
                    conninfo,
                    environment_id=config.environment.environment_id,
                    data_root=prepared.data_root,
                    max_object_bytes=config.artifacts.max_object_bytes,
                    pool_min=config.database.pool_min,
                    pool_max=config.database.pool_max,
                    acquire_timeout_seconds=(
                        config.database.pool_acquire_timeout_seconds
                    ),
                    statement_timeout_seconds=(
                        config.database.statement_timeout_seconds
                    ),
                    authority_admission=authority_admission,
                    query=query,
                    wakeups=wakeups,
                    diagnostic=diagnostic,
                )

            return handle.consume(create)
    except ConfigurationViolation:
        raise LifeRecordQueryViolation("LIFE-QUERY-UNAVAILABLE") from None


def compose_relationship_module(
    prepared: PreparedEnvironment,
    *,
    creator_party_id: UUID,
) -> RelationshipModule:
    """Resolve and bind the one active relationship owner implementation."""

    locator = prepared.effective.config.secret_locators.get(RUNTIME_LOCATOR_NAME)
    if locator is None:
        raise RelationshipViolation("RELATIONSHIP-QUERY-UNAVAILABLE")
    try:
        with prepared.credential_port.resolve(
            locator,
            CredentialPurpose("database.runtime"),
        ) as handle:

            def create(value: memoryview) -> RelationshipModule:
                try:
                    conninfo = bytes(value).decode("utf-8")
                except UnicodeDecodeError:
                    raise RelationshipViolation(
                        "RELATIONSHIP-QUERY-UNAVAILABLE"
                    ) from None
                config = prepared.effective.config
                return bootstrap_relationship(
                    conninfo,
                    expected_role=physical_role_name(
                        config.environment.environment_id, "runtime"
                    ),
                    creator_party_id=creator_party_id,
                    pool_timeout_seconds=config.database.pool_acquire_timeout_seconds,
                )

            return handle.consume(create)
    except ConfigurationViolation:
        raise RelationshipViolation("RELATIONSHIP-QUERY-UNAVAILABLE") from None


def compose_memory_module(
    prepared: PreparedEnvironment,
    *,
    creator_party_id: UUID,
    cursor_key: bytes,
) -> MemoryModule:
    """Resolve and bind the one active subjective-memory owner implementation."""

    locator = prepared.effective.config.secret_locators.get(RUNTIME_LOCATOR_NAME)
    if locator is None:
        raise MemoryViolation("MEMORY-QUERY-UNAVAILABLE")
    try:
        with prepared.credential_port.resolve(
            locator, CredentialPurpose("database.runtime")
        ) as handle:

            def create(value: memoryview) -> MemoryModule:
                try:
                    conninfo = bytes(value).decode("utf-8")
                except UnicodeDecodeError:
                    raise MemoryViolation("MEMORY-QUERY-UNAVAILABLE") from None
                config = prepared.effective.config
                return bootstrap_memory(
                    conninfo,
                    expected_role=physical_role_name(
                        config.environment.environment_id, "runtime"
                    ),
                    environment_id=config.environment.environment_id,
                    creator_party_id=creator_party_id,
                    cursor_key=cursor_key,
                    pool_timeout_seconds=config.database.pool_acquire_timeout_seconds,
                )

            return handle.consume(create)
    except ConfigurationViolation:
        raise MemoryViolation("MEMORY-QUERY-UNAVAILABLE") from None


def compose_sleep_module(
    prepared: PreparedEnvironment,
    *,
    creator_party_id: UUID,
) -> SleepModule:
    """Resolve and bind the one active sleep owner implementation."""

    locator = prepared.effective.config.secret_locators.get(RUNTIME_LOCATOR_NAME)
    if locator is None:
        raise CreatorMaintenanceViolation("MAINTENANCE-QUERY-UNAVAILABLE")
    try:
        with prepared.credential_port.resolve(
            locator,
            CredentialPurpose("database.runtime"),
        ) as handle:

            def create(value: memoryview) -> SleepModule:
                try:
                    conninfo = bytes(value).decode("utf-8")
                except UnicodeDecodeError:
                    raise CreatorMaintenanceViolation(
                        "MAINTENANCE-QUERY-UNAVAILABLE"
                    ) from None
                config = prepared.effective.config
                return bootstrap_sleep(
                    conninfo,
                    expected_role=physical_role_name(
                        config.environment.environment_id, "runtime"
                    ),
                    creator_party_id=creator_party_id,
                    pool_timeout_seconds=config.database.pool_acquire_timeout_seconds,
                )

            return handle.consume(create)
    except ConfigurationViolation:
        raise CreatorMaintenanceViolation("MAINTENANCE-QUERY-UNAVAILABLE") from None


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
    authority_admission: Callable[[], RuntimeFence],
    fetch: ExternalMediaFetchPort,
    evidence: EvidenceWritePort,
    wakeups: WorkWakeupBus,
    diagnostic: Callable[[str], None] | None = None,
) -> PerceptionModule:
    database_locator = prepared.effective.config.secret_locators.get(
        RUNTIME_LOCATOR_NAME
    )
    model_locator = prepared.effective.config.secret_locators.get(MODEL_LOCATOR_NAME)
    speech_locator = prepared.effective.config.secret_locators.get(SPEECH_LOCATOR_NAME)
    if database_locator is None or model_locator is None or speech_locator is None:
        raise ModelViolation("MODEL-CREDENTIAL")
    try:
        with prepared.credential_port.resolve(
            database_locator, CredentialPurpose("database.runtime")
        ) as handle:

            def create(value: memoryview) -> PerceptionModule:
                try:
                    conninfo = bytes(value).decode("utf-8")
                except UnicodeDecodeError:
                    raise ModelViolation("MODEL-DATABASE") from None
                config = prepared.effective.config
                try:
                    recognition_binding = load_external_recognition_binding(
                        runtime_config_path("model-bindings.yaml")
                    )
                except ValueError:
                    raise ModelViolation("MODEL-BINDING-MANIFEST") from None
                factory = PostgreSQLUnitOfWorkFactory(
                    conninfo,
                    environment_id=config.environment.environment_id,
                    pool_min=config.database.pool_min,
                    pool_max=config.database.pool_max,
                    acquire_timeout_seconds=config.database.pool_acquire_timeout_seconds,
                    statement_timeout_seconds=config.database.statement_timeout_seconds,
                    authority_admission=authority_admission,
                )
                return bootstrap_perception(
                    unit_of_work_factory=factory,
                    storage=ContentAddressedArtifactStore(
                        prepared.data_root / "artifacts",
                        max_object_bytes=config.artifacts.max_object_bytes,
                    ),
                    catalog=ArtifactCatalogRepository(),
                    work=PostgreSQLDurableWorkGateway(factory),
                    evidence=evidence,
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

            return handle.consume(create)
    except ConfigurationViolation:
        raise ModelViolation("MODEL-CREDENTIAL") from None


def compose_prompt_module(
    prepared: PreparedEnvironment,
    *,
    creator_party_id: UUID,
    authority_admission: Callable[[], RuntimeFence],
) -> PromptModule:
    """Resolve the Runtime credential for the T-04 Creator Prompt owner."""

    locator = prepared.effective.config.secret_locators.get(RUNTIME_LOCATOR_NAME)
    if locator is None:
        raise CreatorPromptViolation("DB-PROMPT-UNAVAILABLE")
    try:
        with prepared.credential_port.resolve(
            locator,
            CredentialPurpose("database.runtime"),
        ) as handle:

            def create(value: memoryview) -> PromptModule:
                try:
                    conninfo = bytes(value).decode("utf-8")
                except UnicodeDecodeError:
                    raise CreatorPromptViolation("DB-PROMPT-UNAVAILABLE") from None
                config = prepared.effective.config
                catalog = ArtifactCatalogRepository()
                return bootstrap_prompt(
                    creator_party_id=creator_party_id,
                    storage=ContentAddressedArtifactStore(
                        prepared.data_root / "artifacts",
                        max_object_bytes=config.artifacts.max_object_bytes,
                    ),
                    catalog=catalog,
                    unit_of_work_factory=PostgreSQLUnitOfWorkFactory(
                        conninfo,
                        environment_id=config.environment.environment_id,
                        pool_min=config.database.pool_min,
                        pool_max=config.database.pool_max,
                        acquire_timeout_seconds=(
                            config.database.pool_acquire_timeout_seconds
                        ),
                        statement_timeout_seconds=(
                            config.database.statement_timeout_seconds
                        ),
                        authority_admission=authority_admission,
                    ),
                )

            return handle.consume(create)
    except ConfigurationViolation:
        raise CreatorPromptViolation("DB-PROMPT-UNAVAILABLE") from None


def compose_data_rights_module(
    prepared: PreparedEnvironment,
    *,
    creator_party_id: UUID,
    authority_admission: Callable[[], RuntimeFence],
    memory_data_rights: MemoryDataRightsParticipant,
    relationship_data_rights: RelationshipDataRightsParticipant,
    notifier: CreatorProjectionNotifier | None = None,
) -> DataRightsModule:
    locator = prepared.effective.config.secret_locators.get(RUNTIME_LOCATOR_NAME)
    if locator is None:
        raise DataRightsViolation("DATA-RIGHTS-UNAVAILABLE")
    try:
        with prepared.credential_port.resolve(
            locator,
            CredentialPurpose("database.runtime"),
        ) as handle:

            def create(value: memoryview) -> DataRightsModule:
                try:
                    conninfo = bytes(value).decode("utf-8")
                except UnicodeDecodeError:
                    raise DataRightsViolation("DATA-RIGHTS-UNAVAILABLE") from None
                config = prepared.effective.config
                def factory() -> PostgreSQLUnitOfWorkFactory:
                    return PostgreSQLUnitOfWorkFactory(
                        conninfo,
                        environment_id=config.environment.environment_id,
                        pool_min=config.database.pool_min,
                        pool_max=config.database.pool_max,
                        acquire_timeout_seconds=(
                            config.database.pool_acquire_timeout_seconds
                        ),
                        statement_timeout_seconds=(
                            config.database.statement_timeout_seconds
                        ),
                        authority_admission=authority_admission,
                    )

                return bootstrap_data_rights(
                    creator_party_id=creator_party_id,
                    data_root=prepared.data_root,
                    order_factory=factory(),
                    export_factory=factory(),
                    storage=ContentAddressedArtifactStore(
                        prepared.data_root / "artifacts",
                        max_object_bytes=config.artifacts.max_object_bytes,
                    ),
                    memory=memory_data_rights,
                    relationship=relationship_data_rights,
                    notifier=notifier,
                )

            return handle.consume(create)
    except ConfigurationViolation:
        raise DataRightsViolation("DATA-RIGHTS-UNAVAILABLE") from None


def compose_life_opportunity_pipeline(
    prepared: PreparedEnvironment,
    *,
    authority_admission: Callable[[], RuntimeFence],
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

    locator = prepared.effective.config.secret_locators.get(RUNTIME_LOCATOR_NAME)
    if locator is None:
        raise LifeViolation("LIFE-DATABASE")
    try:
        with prepared.credential_port.resolve(
            locator,
            CredentialPurpose("database.runtime"),
        ) as handle:

            def create(value: memoryview) -> OpportunityRuntimePort:
                try:
                    conninfo = bytes(value).decode("utf-8")
                except UnicodeDecodeError:
                    raise LifeViolation("LIFE-DATABASE") from None
                config = prepared.effective.config
                factory = PostgreSQLUnitOfWorkFactory(
                    conninfo,
                    environment_id=config.environment.environment_id,
                    pool_min=config.database.pool_min,
                    pool_max=config.database.pool_max,
                    acquire_timeout_seconds=(
                        config.database.pool_acquire_timeout_seconds
                    ),
                    statement_timeout_seconds=(
                        config.database.statement_timeout_seconds
                    ),
                    authority_admission=authority_admission,
                )
                return bootstrap_opportunity(
                    factory=factory,
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
                    maintenance_deadline_seconds=(
                        config.maintenance.deadline_after_seconds
                    ),
                )

            return handle.consume(create)
    except ConfigurationViolation:
        raise LifeViolation("LIFE-DATABASE") from None


def compose_context_pipeline(
    prepared: PreparedEnvironment,
    *,
    authority_admission: Callable[[], RuntimeFence],
    activity_read: ActivityReadPort,
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

    locator = prepared.effective.config.secret_locators.get(RUNTIME_LOCATOR_NAME)
    embedding_locator = (
        prepared.effective.config.secret_locators.get(MODEL_LOCATOR_NAME)
        if prepared.effective.config.model.semantic_recall_enabled
        else None
    )
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

            def create(value: memoryview) -> ContextRuntimePort:
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
                factory = PostgreSQLUnitOfWorkFactory(
                    conninfo,
                    environment_id=config.environment.environment_id,
                    pool_min=config.database.pool_min,
                    pool_max=config.database.pool_max,
                    acquire_timeout_seconds=(
                        config.database.pool_acquire_timeout_seconds
                    ),
                    statement_timeout_seconds=(
                        config.database.statement_timeout_seconds
                    ),
                    authority_admission=authority_admission,
                )
                return bootstrap_context(
                    factory=factory,
                    storage=ContentAddressedArtifactStore(
                        prepared.data_root / "artifacts",
                        max_object_bytes=config.artifacts.max_object_bytes,
                    ),
                    catalog=ArtifactCatalogRepository(),
                    work=PostgreSQLDurableWorkGateway(factory),
                    activity_read=activity_read,
                    memory_read=memory_read,
                    memory_projection=memory_projection,
                    mood_read=mood_read,
                    prompt_read=prompt_read,
                    material_projection=material_projection,
                    relationship_read=relationship_read,
                    sleep_read=sleep_read,
                    subject_state_read=subject_state_read,
                    web_search_active=prepared.effective.config.web.enabled,
                    wakeups=wakeups,
                    diagnostic=diagnostic,
                    embedding=(
                        VolcengineArkEmbeddingAdapter(
                            binding=load_embedding_binding(
                                runtime_config_path("model-bindings.yaml")
                            ),
                            credential_port=prepared.credential_port,
                            locator=embedding_locator,
                        )
                        if embedding_locator is not None
                        else None
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


def compose_context_embedding_pipeline(
    prepared: PreparedEnvironment,
    *,
    authority_admission: Callable[[], RuntimeFence],
    memory_projection: MemoryProjectionPort,
    material_projection: MaterialProjectionPort,
) -> ContextEmbeddingRuntimePort:
    database_locator = prepared.effective.config.secret_locators.get(
        RUNTIME_LOCATOR_NAME
    )
    embedding_locator = prepared.effective.config.secret_locators.get(
        MODEL_LOCATOR_NAME
    )
    if database_locator is None or embedding_locator is None:
        raise ModelViolation("MODEL-CREDENTIAL")
    try:
        with prepared.credential_port.resolve(
            database_locator, CredentialPurpose("database.runtime")
        ) as handle:

            def create(value: memoryview) -> ContextEmbeddingRuntimePort:
                try:
                    conninfo = bytes(value).decode("utf-8")
                except UnicodeDecodeError:
                    raise ModelViolation("MODEL-DATABASE") from None
                config = prepared.effective.config
                factory = PostgreSQLUnitOfWorkFactory(
                    conninfo,
                    environment_id=config.environment.environment_id,
                    pool_min=config.database.pool_min,
                    pool_max=config.database.pool_max,
                    acquire_timeout_seconds=config.database.pool_acquire_timeout_seconds,
                    statement_timeout_seconds=config.database.statement_timeout_seconds,
                    authority_admission=authority_admission,
                )
                return bootstrap_context_embedding(
                    factory=factory,
                    storage=ContentAddressedArtifactStore(
                        prepared.data_root / "artifacts",
                        max_object_bytes=config.artifacts.max_object_bytes,
                    ),
                    adapter=VolcengineArkEmbeddingAdapter(
                        binding=load_embedding_binding(
                            runtime_config_path("model-bindings.yaml")
                        ),
                        credential_port=prepared.credential_port,
                        locator=embedding_locator,
                    ),
                    work=PostgreSQLDurableWorkGateway(factory),
                    memories=memory_projection,
                    materials=material_projection,
                )

            return handle.consume(create)
    except ConfigurationViolation:
        raise ModelViolation("MODEL-CREDENTIAL") from None


def compose_model_pipeline(
    prepared: PreparedEnvironment,
    *,
    authority_admission: Callable[[], RuntimeFence],
    wakeups: WorkWakeupBus | None = None,
    diagnostic: Callable[[str], None] | None = None,
) -> CognitionWorkerPort:
    """Resolve the Runtime and model credentials for the active S024 worker."""

    database_locator = prepared.effective.config.secret_locators.get(
        RUNTIME_LOCATOR_NAME
    )
    model_locator = prepared.effective.config.secret_locators.get(MODEL_LOCATOR_NAME)
    if database_locator is None or model_locator is None:
        raise ModelViolation("MODEL-CREDENTIAL")
    try:
        with prepared.credential_port.resolve(
            database_locator,
            CredentialPurpose("database.runtime"),
        ) as handle:

            def create(value: memoryview) -> CognitionWorkerPort:
                try:
                    conninfo = bytes(value).decode("utf-8")
                except UnicodeDecodeError:
                    raise ModelViolation("MODEL-DATABASE") from None
                config = prepared.effective.config
                factory = PostgreSQLUnitOfWorkFactory(
                    conninfo,
                    environment_id=config.environment.environment_id,
                    pool_min=config.database.pool_min,
                    pool_max=config.database.pool_max,
                    acquire_timeout_seconds=(
                        config.database.pool_acquire_timeout_seconds
                    ),
                    statement_timeout_seconds=(
                        config.database.statement_timeout_seconds
                    ),
                    authority_admission=authority_admission,
                )

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
                    factory=factory,
                    storage=ContentAddressedArtifactStore(
                        prepared.data_root / "artifacts",
                        max_object_bytes=config.artifacts.max_object_bytes,
                    ),
                    catalog=ArtifactCatalogRepository(),
                    work=PostgreSQLDurableWorkGateway(factory),
                    adapter_factory=adapter_factory,
                    binding_path=runtime_config_path("model-bindings.yaml"),
                    web_search_active=prepared.effective.config.web.enabled,
                    wakeups=wakeups,
                    diagnostic=diagnostic,
                )

            return handle.consume(create)
    except ConfigurationViolation:
        raise ModelViolation("MODEL-CREDENTIAL") from None


def compose_web_search_pipeline(
    prepared: PreparedEnvironment,
    *,
    authority_admission: Callable[[], RuntimeFence],
    evidence: EvidenceWritePort,
    diagnostic: Callable[[str], None] | None = None,
) -> WebObservationRuntimePort:
    """Resolve the fixed database and Ark credentials for S033 custody."""

    database_locator = prepared.effective.config.secret_locators.get(
        RUNTIME_LOCATOR_NAME
    )
    model_locator = prepared.effective.config.secret_locators.get(MODEL_LOCATOR_NAME)
    if database_locator is None or model_locator is None:
        raise WebObservationViolation("WEB-CREDENTIAL")
    try:
        manifest_bytes = runtime_config_path("web-search.yaml").read_bytes()
    except OSError:
        raise WebObservationViolation("WEB-MANIFEST") from None
    try:
        with prepared.credential_port.resolve(
            database_locator,
            CredentialPurpose("database.runtime"),
        ) as handle:

            def create(value: memoryview) -> WebObservationRuntimePort:
                try:
                    conninfo = bytes(value).decode("utf-8")
                except UnicodeDecodeError:
                    raise WebObservationViolation("WEB-DATABASE") from None
                config = prepared.effective.config
                factory = PostgreSQLUnitOfWorkFactory(
                    conninfo,
                    environment_id=config.environment.environment_id,
                    pool_min=config.database.pool_min,
                    pool_max=config.database.pool_max,
                    acquire_timeout_seconds=(
                        config.database.pool_acquire_timeout_seconds
                    ),
                    statement_timeout_seconds=(
                        config.database.statement_timeout_seconds
                    ),
                    authority_admission=authority_admission,
                )
                return bootstrap_web_observation(
                    factory=factory,
                    storage=ContentAddressedArtifactStore(
                        prepared.data_root / "artifacts",
                        max_object_bytes=config.artifacts.max_object_bytes,
                    ),
                    catalog=ArtifactCatalogRepository(),
                    work=PostgreSQLDurableWorkGateway(factory),
                    credential_port=prepared.credential_port,
                    credential_locator=model_locator,
                    manifest_bytes=manifest_bytes,
                    evidence=evidence,
                    diagnostic=diagnostic,
                )

            return handle.consume(create)
    except ConfigurationViolation:
        raise WebObservationViolation("WEB-CREDENTIAL") from None


def compose_web_research_admission_pipeline(
    prepared: PreparedEnvironment,
    *,
    authority_admission: Callable[[], RuntimeFence],
    custody: WebObservationRuntimePort,
    evidence: EvidenceWritePort,
    diagnostic: Callable[[str], None] | None = None,
) -> WebResearchRuntimePort:
    """Resolve the active S034 intent-to-custody worker."""

    database_locator = prepared.effective.config.secret_locators.get(
        RUNTIME_LOCATOR_NAME
    )
    if database_locator is None:
        raise WebResearchViolation("WEB-RESEARCH-DATABASE")
    try:
        with prepared.credential_port.resolve(
            database_locator,
            CredentialPurpose("database.runtime"),
        ) as handle:

            def create(value: memoryview) -> WebResearchRuntimePort:
                try:
                    conninfo = bytes(value).decode("utf-8")
                except UnicodeDecodeError:
                    raise WebResearchViolation("WEB-RESEARCH-DATABASE") from None
                config = prepared.effective.config
                factory = PostgreSQLUnitOfWorkFactory(
                    conninfo,
                    environment_id=config.environment.environment_id,
                    pool_min=config.database.pool_min,
                    pool_max=config.database.pool_max,
                    acquire_timeout_seconds=(
                        config.database.pool_acquire_timeout_seconds
                    ),
                    statement_timeout_seconds=(
                        config.database.statement_timeout_seconds
                    ),
                    authority_admission=authority_admission,
                )
                return bootstrap_web_research(
                    factory=factory,
                    storage=ContentAddressedArtifactStore(
                        prepared.data_root / "artifacts",
                        max_object_bytes=config.artifacts.max_object_bytes,
                    ),
                    work=PostgreSQLDurableWorkGateway(factory),
                    custody=custody,
                    evidence=evidence,
                    diagnostic=diagnostic,
                )

            return handle.consume(create)
    except ConfigurationViolation:
        raise WebResearchViolation("WEB-RESEARCH-DATABASE") from None


def compose_candidate_validation_pipeline(
    prepared: PreparedEnvironment,
    *,
    authority_admission: Callable[[], RuntimeFence],
    activity_cognition: ActivityCognitionPort,
    activity_read: ActivityReadPort,
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

    locator = prepared.effective.config.secret_locators.get(RUNTIME_LOCATOR_NAME)
    if locator is None:
        raise CandidateViolation("CANDIDATE-DATABASE")
    try:
        with prepared.credential_port.resolve(
            locator,
            CredentialPurpose("database.runtime"),
        ) as handle:

            def create(value: memoryview) -> CognitionWorkerPort:
                try:
                    conninfo = bytes(value).decode("utf-8")
                except UnicodeDecodeError:
                    raise CandidateViolation("CANDIDATE-DATABASE") from None
                config = prepared.effective.config
                factory = PostgreSQLUnitOfWorkFactory(
                    conninfo,
                    environment_id=config.environment.environment_id,
                    pool_min=config.database.pool_min,
                    pool_max=config.database.pool_max,
                    acquire_timeout_seconds=(
                        config.database.pool_acquire_timeout_seconds
                    ),
                    statement_timeout_seconds=(
                        config.database.statement_timeout_seconds
                    ),
                    authority_admission=authority_admission,
                )
                return bootstrap_cognition_candidate(
                    factory=factory,
                    storage=ContentAddressedArtifactStore(
                        prepared.data_root / "artifacts",
                        max_object_bytes=config.artifacts.max_object_bytes,
                    ),
                    catalog=ArtifactCatalogRepository(),
                    work=PostgreSQLDurableWorkGateway(factory),
                    activity_cognition=activity_cognition,
                    activity_read=activity_read,
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
                    web_search_active=prepared.effective.config.web.enabled,
                    wakeups=wakeups,
                    diagnostic=diagnostic,
                )

            return handle.consume(create)
    except ConfigurationViolation:
        raise CandidateViolation("CANDIDATE-DATABASE") from None


def compose_subject_commit_pipeline(
    prepared: PreparedEnvironment,
    *,
    authority_admission: Callable[[], RuntimeFence],
    activity_cognition: ActivityCognitionPort,
    activity_commit: ActivityCommitPort,
    capability_commit: CapabilityCommitPort,
    capability_read: CapabilityReadPort,
    evidence: EvidenceWritePort,
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
    relationship_read: RelationshipReadPort,
    relationship_policy: RelationshipPolicyPort,
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

    locator = prepared.effective.config.secret_locators.get(RUNTIME_LOCATOR_NAME)
    if locator is None:
        raise SubjectCommitViolation("SUBJECT-DATABASE")
    try:
        with prepared.credential_port.resolve(
            locator,
            CredentialPurpose("database.runtime"),
        ) as handle:

            def create(value: memoryview) -> SubjectCommitPipeline:
                try:
                    conninfo = bytes(value).decode("utf-8")
                except UnicodeDecodeError:
                    raise SubjectCommitViolation("SUBJECT-DATABASE") from None
                config = prepared.effective.config
                expression = bootstrap_expression(
                    relationship_read,
                    relationship_policy,
                    bootstrap_expression_effect_registration(),
                )
                return build_subject_commit_pipeline(
                    conninfo,
                    environment_id=config.environment.environment_id,
                    data_root=prepared.data_root,
                    max_object_bytes=config.artifacts.max_object_bytes,
                    pool_min=config.database.pool_min,
                    pool_max=config.database.pool_max,
                    acquire_timeout_seconds=config.database.pool_acquire_timeout_seconds,
                    statement_timeout_seconds=config.database.statement_timeout_seconds,
                    authority_admission=authority_admission,
                    activity_cognition=activity_cognition,
                    activity_commit=activity_commit,
                    capability_commit=capability_commit,
                    capability_read=capability_read,
                    codex_commit=bootstrap_codex_commit(),
                    evidence=evidence,
                    expression_commit=expression.commit,
                    memory_commit=memory_commit,
                    memory_cognition=memory_cognition,
                    mood_commit=mood_commit,
                    mood_cognition=mood_cognition,
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

            return handle.consume(create)
    except ConfigurationViolation:
        raise SubjectCommitViolation("SUBJECT-DATABASE") from None


def compose_effect_grant_cancellation() -> EffectGrantCancellationPort:
    return bootstrap_effect_grant_cancellation()


def compose_capability_policy(
    prepared: PreparedEnvironment,
    *,
    authority_admission: Callable[[], RuntimeFence],
    cursor_key: bytes,
    effect_cancellation: EffectGrantCancellationPort,
    notifier: CreatorProjectionNotifier | None = None,
) -> CapabilityModule:
    """Resolve the Runtime credential for the sole active T-04 policy."""

    locator = prepared.effective.config.secret_locators.get(RUNTIME_LOCATOR_NAME)
    if locator is None:
        raise CapabilityViolation("POLICY-DATABASE")
    try:
        with prepared.credential_port.resolve(
            locator, CredentialPurpose("database.runtime")
        ) as handle:

            def create(value: memoryview) -> CapabilityModule:
                try:
                    conninfo = bytes(value).decode("utf-8")
                except UnicodeDecodeError:
                    raise CapabilityViolation("POLICY-DATABASE") from None
                config = prepared.effective.config
                factory = PostgreSQLUnitOfWorkFactory(
                    conninfo,
                    environment_id=config.environment.environment_id,
                    pool_min=config.database.pool_min,
                    pool_max=config.database.pool_max,
                    acquire_timeout_seconds=config.database.pool_acquire_timeout_seconds,
                    statement_timeout_seconds=config.database.statement_timeout_seconds,
                    authority_admission=authority_admission,
                )
                return bootstrap_capability(
                    factory,
                    environment_id=config.environment.environment_id,
                    cursor_key=cursor_key,
                    effect_cancellation=effect_cancellation,
                    notifier=notifier,
                )

            return handle.consume(create)
    except ConfigurationViolation:
        raise CapabilityViolation("POLICY-DATABASE") from None


def compose_response_admission_pipeline(
    prepared: PreparedEnvironment,
    *,
    authority_admission: Callable[[], RuntimeFence],
    wakeups: WorkWakeupBus,
    diagnostic: Callable[[str], None] | None = None,
) -> ResponseAdmissionRuntimePort:
    """Resolve the Runtime credential for the S028 admission worker."""

    locator = prepared.effective.config.secret_locators.get(RUNTIME_LOCATOR_NAME)
    if locator is None:
        raise ResponseViolation("RESPONSE-DATABASE")
    try:
        with prepared.credential_port.resolve(
            locator, CredentialPurpose("database.runtime")
        ) as handle:

            def create(value: memoryview) -> ResponseAdmissionRuntimePort:
                try:
                    conninfo = bytes(value).decode("utf-8")
                except UnicodeDecodeError:
                    raise ResponseViolation("RESPONSE-DATABASE") from None
                config = prepared.effective.config
                factory = PostgreSQLUnitOfWorkFactory(
                    conninfo,
                    environment_id=config.environment.environment_id,
                    pool_min=config.database.pool_min,
                    pool_max=config.database.pool_max,
                    acquire_timeout_seconds=config.database.pool_acquire_timeout_seconds,
                    statement_timeout_seconds=config.database.statement_timeout_seconds,
                    authority_admission=authority_admission,
                )
                return bootstrap_response_admission(
                    factory=factory,
                    storage=ContentAddressedArtifactStore(
                        prepared.data_root / "artifacts",
                        max_object_bytes=config.artifacts.max_object_bytes,
                    ),
                    work=PostgreSQLDurableWorkGateway(factory),
                    wakeups=wakeups,
                    diagnostic=diagnostic,
                )

            return handle.consume(create)
    except ConfigurationViolation:
        raise ResponseViolation("RESPONSE-DATABASE") from None


def compose_runtime_recovery(
    prepared: PreparedEnvironment,
    *,
    authority_admission: Callable[[], RuntimeFence],
    mood_read: MoodReadPort,
    prompt_read: PromptReadPort,
    subject_state_read: SubjectStateReadPort,
) -> PostgreSQLRuntimeRecovery:
    """Resolve the Runtime credential for the fenced startup recovery gateway."""

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

            def create(value: memoryview) -> PostgreSQLRuntimeRecovery:
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
                return PostgreSQLRuntimeRecovery(
                    conninfo,
                    environment_id=config.environment.environment_id,
                    data_root=prepared.data_root,
                    max_object_bytes=config.artifacts.max_object_bytes,
                    pool_timeout_seconds=(config.database.pool_acquire_timeout_seconds),
                    authority_admission=authority_admission,
                    mood=mood_read,
                    prompts=prompt_read,
                    subject_state=subject_state_read,
                )

            return handle.consume(create)
    except ConfigurationViolation:
        raise DatabaseViolation(
            "DB-ROLE-CREDENTIAL-SCOPE",
            "the configured PostgreSQL connection is unavailable",
            status="unavailable",
            exit_code=3,
        ) from None


def compose_effect_registration_pipeline(
    prepared: PreparedEnvironment,
    *,
    authority_admission: Callable[[], RuntimeFence],
    capability_consumption: CapabilityGrantConsumptionPort,
    notifier: CreatorProjectionNotifier | None = None,
    wakeups: WorkWakeupBus,
    diagnostic: Callable[[str], None] | None = None,
    fault_injector: Callable[[str], None] | None = None,
    external_message_adapter: ActionAdapterPort | None = None,
) -> EffectRuntimePort:
    """Resolve the Runtime credential for the S029 T-05 worker."""

    locator = prepared.effective.config.secret_locators.get(RUNTIME_LOCATOR_NAME)
    if locator is None:
        raise EffectViolation("EFFECT-DATABASE")
    try:
        with prepared.credential_port.resolve(
            locator, CredentialPurpose("database.runtime")
        ) as handle:

            def create(value: memoryview) -> EffectRuntimePort:
                try:
                    conninfo = bytes(value).decode("utf-8")
                except UnicodeDecodeError:
                    raise EffectViolation("EFFECT-DATABASE") from None
                config = prepared.effective.config
                factory = PostgreSQLUnitOfWorkFactory(
                    conninfo,
                    environment_id=config.environment.environment_id,
                    pool_min=config.database.pool_min,
                    pool_max=config.database.pool_max,
                    acquire_timeout_seconds=config.database.pool_acquire_timeout_seconds,
                    statement_timeout_seconds=config.database.statement_timeout_seconds,
                    authority_admission=authority_admission,
                )
                return bootstrap_effect_runtime(
                    factory=factory,
                    storage=ContentAddressedArtifactStore(
                        prepared.data_root / "artifacts",
                        max_object_bytes=config.artifacts.max_object_bytes,
                    ),
                    work=PostgreSQLDurableWorkGateway(factory),
                    capability_consumption=capability_consumption,
                    notifier=notifier,
                    wakeups=wakeups,
                    diagnostic=diagnostic,
                    fault_injector=fault_injector,
                    external_message_adapter=external_message_adapter,
                )

            return handle.consume(create)
    except ConfigurationViolation:
        raise EffectViolation("EFFECT-DATABASE") from None


def compose_codex_pipeline(
    prepared: PreparedEnvironment,
    *,
    creator_party_id: UUID,
    creator_input: CreatorInputTransactionPort,
    evidence: EvidenceWritePort,
    authority_admission: Callable[[], RuntimeFence],
    notifier: CreatorProjectionNotifier | None = None,
    diagnostic: Callable[[str], None] | None = None,
) -> CodexRuntimePort:
    """Compose the one active S039 Codex dispatcher without exposing auth."""

    database_locator = prepared.effective.config.secret_locators.get(
        RUNTIME_LOCATOR_NAME
    )
    auth_locator = prepared.effective.config.secret_locators.get(CODEX_LOCATOR_NAME)
    if database_locator is None or auth_locator is None:
        raise CodexDelegationViolation("CODEX-DELEGATION-CREDENTIAL")
    try:
        with prepared.credential_port.resolve(
            database_locator, CredentialPurpose("database.runtime")
        ) as handle:

            def create(value: memoryview) -> CodexRuntimePort:
                try:
                    conninfo = bytes(value).decode("utf-8")
                except UnicodeDecodeError:
                    raise CodexDelegationViolation(
                        "CODEX-DELEGATION-DATABASE"
                    ) from None
                config = prepared.effective.config

                factory = PostgreSQLUnitOfWorkFactory(
                    conninfo,
                    environment_id=config.environment.environment_id,
                    pool_min=config.database.pool_min,
                    pool_max=config.database.pool_max,
                    acquire_timeout_seconds=config.database.pool_acquire_timeout_seconds,
                    statement_timeout_seconds=config.database.statement_timeout_seconds,
                    authority_admission=authority_admission,
                )
                run_root = prepared.data_root / "codex-runner"
                return bootstrap_codex(
                    factory=factory,
                    storage=ContentAddressedArtifactStore(
                        prepared.data_root / "artifacts",
                        max_object_bytes=config.artifacts.max_object_bytes,
                    ),
                    catalog=ArtifactCatalogRepository(),
                    environment_root=prepared.root,
                    run_root=run_root,
                    creator_party_id=creator_party_id,
                    creator_input=creator_input,
                    evidence=evidence,
                    dispatch_boundary=bootstrap_effect_dispatch_boundary(),
                    runner_entry_module="armi_runtime.codex_runner_cli",
                    notifier=notifier,
                    diagnostic=diagnostic,
                )

            return handle.consume(create)
    except ConfigurationViolation:
        raise CodexDelegationViolation("CODEX-DELEGATION-CREDENTIAL") from None


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
    "compose_context_pipeline",
    "compose_data_rights_module",
    "compose_effect_grant_cancellation",
    "compose_effect_registration_pipeline",
    "compose_evidence_module",
    "compose_exact_life_query_pipeline",
    "compose_interaction_module",
    "compose_life_opportunity_pipeline",
    "compose_life_record_query",
    "compose_material_module",
    "compose_memory_module",
    "compose_model_pipeline",
    "compose_mood_module",
    "compose_other_human_record_query",
    "compose_perception_module",
    "compose_prompt_module",
    "compose_relationship_module",
    "compose_response_admission_pipeline",
    "compose_runtime_authority",
    "compose_runtime_observation",
    "compose_runtime_recovery",
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
