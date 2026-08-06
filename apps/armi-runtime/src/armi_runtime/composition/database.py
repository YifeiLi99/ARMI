"""Explicit database composition for Runtime probing and empty-database install."""

from __future__ import annotations

from collections.abc import Callable
from importlib.resources import files
from typing import Final
from uuid import UUID

from armi_kernel.application import (
    CandidateViolation,
    CapabilityViolation,
    CodexDelegationViolation,
    CreatorActivityViolation,
    CreatorMaintenanceViolation,
    CreatorProjectionNotifier,
    CreatorPromptViolation,
    CreatorRelationshipViolation,
    CredentialPort,
    CredentialPurpose,
    LifeRecordQueryPort,
    LifeRecordQueryViolation,
    LifeViolation,
    ModelViolation,
    ResponseViolation,
    RuntimeFence,
    SubjectCommitViolation,
    WebObservationViolation,
    WebResearchViolation,
)
from armi_kernel.contracts import Digest

from armi_runtime.adapters.artifacts.content_store import ContentAddressedArtifactStore
from armi_runtime.adapters.creator_identity import CreatorContext, read_creator_context
from armi_runtime.adapters.persistence.birth import (
    ContinuityState,
    probe_continuity,
)
from armi_runtime.adapters.persistence.capability_policy import (
    PostgreSQLCreatorGrantPolicy,
)
from armi_runtime.adapters.persistence.creator_activities import (
    PostgreSQLCreatorActivityQuery,
)
from armi_runtime.adapters.persistence.creator_maintenance import (
    PostgreSQLCreatorMaintenanceQuery,
)
from armi_runtime.adapters.persistence.creator_relationships import (
    PostgreSQLCreatorRelationshipQuery,
)
from armi_runtime.adapters.persistence.life_records import PostgreSQLLifeRecordQuery
from armi_runtime.adapters.persistence.recovery import (
    PostgreSQLRuntimeRecovery,
)
from armi_runtime.adapters.persistence.runtime_authority import (
    PostgreSQLRuntimeAuthority,
)
from armi_runtime.adapters.persistence.runtime_observability import (
    PostgreSQLRuntimeObservation,
)
from armi_runtime.adapters.persistence.scene_timeline import (
    PostgreSQLSceneTimelineQuery,
)
from armi_runtime.adapters.persistence.schema_gateway import (
    DatabaseViolation,
    PostgreSQLSchemaGateway,
    SchemaStatus,
)
from armi_runtime.adapters.persistence.unit_of_work import PostgreSQLUnitOfWorkFactory

from .birth_manifest import packaged_birth_digests
from .candidate_pipeline import (
    CandidateValidationPipeline,
    build_candidate_validation_pipeline,
)
from .candidate_validator import CANDIDATE_POLICY_VERSION
from .codex_pipeline import CodexEffectPipeline
from .configuration import ConfigurationViolation
from .context_compiler import CONTEXT_POLICY_VERSION
from .context_pipeline import ContextPipeline, build_context_pipeline
from .creator_input import (
    EvidenceAcceptanceTransaction,
    build_evidence_acceptance_transaction,
)
from .creator_prompts import CreatorPromptService, build_creator_prompt_service
from .effect_pipeline import (
    EffectRegistrationPipeline,
    build_effect_registration_pipeline,
)
from .environment import PreparedEnvironment
from .exact_life_query_pipeline import (
    ExactLifeQueryPipeline,
    build_exact_life_query_pipeline,
)
from .life_opportunity import (
    LifeOpportunityPipeline,
    build_life_opportunity_pipeline,
)
from .model_pipeline import ModelPipeline, build_model_pipeline
from .response_pipeline import (
    ResponseAdmissionPipeline,
    build_response_admission_pipeline,
)
from .subject_commit_pipeline import (
    SubjectCommitPipeline,
    build_subject_commit_pipeline,
)
from .web_research_pipeline import (
    WebResearchAdmissionPipeline,
    build_web_research_admission_pipeline,
)
from .web_search_pipeline import WebSearchPipeline, build_web_search_pipeline
from .work_wakeup import WorkWakeupBus

RUNTIME_LOCATOR_NAME: Final = "database.runtime"
MIGRATOR_LOCATOR_NAME: Final = "database.migrator"
MODEL_LOCATOR_NAME: Final = "model.ark_api_key"
CODEX_LOCATOR_NAME: Final = "codex.auth_json"

_REASON_BY_CODE: Final = {
    "DB-CONNECTION-UNAVAILABLE": "RUNTIME_DATABASE_UNAVAILABLE",
    "DB-PG-VERSION": "RUNTIME_DATABASE_VERSION_MISMATCH",
    "DB-DATABASE-IDENTITY": "RUNTIME_DATABASE_IDENTITY_MISMATCH",
    "DB-RUNTIME-ROLE-UNSAFE": "RUNTIME_DATABASE_ROLE_UNSAFE",
    "DB-SCHEMA-MISSING": "RUNTIME_SCHEMA_MISSING",
    "DB-SCHEMA-EXISTS": "RUNTIME_SCHEMA_INVALID",
    "DB-SCHEMA-DIRTY": "RUNTIME_SCHEMA_INVALID",
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
    """Read-only Runtime probe; this path cannot install the current schema."""

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
                return probe_continuity(
                    conninfo,
                    composition_digest=digests["composition_digest"],
                    birth_contract_digest=digests["birth_contract_digest"],
                    creator_asset_digest=digests["creator_asset_manifest_digest"],
                )

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


def compose_scene_timeline_query(
    prepared: PreparedEnvironment,
    *,
    creator_party_id: UUID,
    cursor_key: bytes,
) -> PostgreSQLSceneTimelineQuery:
    """Resolve the Runtime credential for the dedicated read-only query pool."""

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

            def create(value: memoryview) -> PostgreSQLSceneTimelineQuery:
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
                return PostgreSQLSceneTimelineQuery(
                    conninfo,
                    environment_id=config.environment.environment_id,
                    creator_party_id=creator_party_id,
                    cursor_key=cursor_key,
                    pool_timeout_seconds=config.database.pool_acquire_timeout_seconds,
                )

            return handle.consume(create)
    except ConfigurationViolation:
        raise DatabaseViolation(
            "DB-ROLE-CREDENTIAL-SCOPE",
            "the configured PostgreSQL connection is unavailable",
            status="unavailable",
            exit_code=3,
        ) from None


def compose_creator_activity_query(
    prepared: PreparedEnvironment,
    *,
    creator_party_id: UUID,
) -> PostgreSQLCreatorActivityQuery:
    """Resolve the Runtime credential for the bounded Activity projection."""

    locator = prepared.effective.config.secret_locators.get(RUNTIME_LOCATOR_NAME)
    if locator is None:
        raise CreatorActivityViolation("ACTIVITY-QUERY-UNAVAILABLE")
    try:
        with prepared.credential_port.resolve(
            locator,
            CredentialPurpose("database.runtime"),
        ) as handle:

            def create(value: memoryview) -> PostgreSQLCreatorActivityQuery:
                try:
                    conninfo = bytes(value).decode("utf-8")
                except UnicodeDecodeError:
                    raise CreatorActivityViolation(
                        "ACTIVITY-QUERY-UNAVAILABLE"
                    ) from None
                config = prepared.effective.config
                return PostgreSQLCreatorActivityQuery(
                    conninfo,
                    environment_id=config.environment.environment_id,
                    creator_party_id=creator_party_id,
                    pool_timeout_seconds=config.database.pool_acquire_timeout_seconds,
                )

            return handle.consume(create)
    except ConfigurationViolation:
        raise CreatorActivityViolation("ACTIVITY-QUERY-UNAVAILABLE") from None


def compose_life_record_query(
    prepared: PreparedEnvironment,
    *,
    creator_party_id: UUID,
    cursor_key: bytes,
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
                    data_root=prepared.data_root,
                    max_object_bytes=config.artifacts.max_object_bytes,
                    pool_timeout_seconds=config.database.pool_acquire_timeout_seconds,
                )

            return handle.consume(create)
    except ConfigurationViolation:
        raise LifeRecordQueryViolation("LIFE-QUERY-UNAVAILABLE") from None


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
                    raise LifeRecordQueryViolation(
                        "LIFE-QUERY-UNAVAILABLE"
                    ) from None
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


def compose_creator_relationship_query(
    prepared: PreparedEnvironment,
    *,
    creator_party_id: UUID,
) -> PostgreSQLCreatorRelationshipQuery:
    """Resolve the Runtime credential for the bounded relationship projection."""

    locator = prepared.effective.config.secret_locators.get(RUNTIME_LOCATOR_NAME)
    if locator is None:
        raise CreatorRelationshipViolation("RELATIONSHIP-QUERY-UNAVAILABLE")
    try:
        with prepared.credential_port.resolve(
            locator,
            CredentialPurpose("database.runtime"),
        ) as handle:

            def create(value: memoryview) -> PostgreSQLCreatorRelationshipQuery:
                try:
                    conninfo = bytes(value).decode("utf-8")
                except UnicodeDecodeError:
                    raise CreatorRelationshipViolation(
                        "RELATIONSHIP-QUERY-UNAVAILABLE"
                    ) from None
                config = prepared.effective.config
                return PostgreSQLCreatorRelationshipQuery(
                    conninfo,
                    environment_id=config.environment.environment_id,
                    creator_party_id=creator_party_id,
                    pool_timeout_seconds=config.database.pool_acquire_timeout_seconds,
                )

            return handle.consume(create)
    except ConfigurationViolation:
        raise CreatorRelationshipViolation("RELATIONSHIP-QUERY-UNAVAILABLE") from None


def compose_creator_maintenance_query(
    prepared: PreparedEnvironment,
    *,
    creator_party_id: UUID,
) -> PostgreSQLCreatorMaintenanceQuery:
    """Resolve the Runtime credential for the maintenance projection."""

    locator = prepared.effective.config.secret_locators.get(RUNTIME_LOCATOR_NAME)
    if locator is None:
        raise CreatorMaintenanceViolation("MAINTENANCE-QUERY-UNAVAILABLE")
    try:
        with prepared.credential_port.resolve(
            locator,
            CredentialPurpose("database.runtime"),
        ) as handle:

            def create(value: memoryview) -> PostgreSQLCreatorMaintenanceQuery:
                try:
                    conninfo = bytes(value).decode("utf-8")
                except UnicodeDecodeError:
                    raise CreatorMaintenanceViolation(
                        "MAINTENANCE-QUERY-UNAVAILABLE"
                    ) from None
                config = prepared.effective.config
                return PostgreSQLCreatorMaintenanceQuery(
                    conninfo,
                    environment_id=config.environment.environment_id,
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
                    expected_bundle_digest=prepared.composition.digest,
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


def compose_creator_input(
    prepared: PreparedEnvironment,
    *,
    creator_party_id: UUID,
    authority_admission: Callable[[], RuntimeFence],
    notifier: CreatorProjectionNotifier | None,
    wakeups: WorkWakeupBus | None = None,
    diagnostic: Callable[[str], None] | None = None,
    fault_injector: Callable[[str], None] | None = None,
) -> EvidenceAcceptanceTransaction:
    """Resolve the Runtime credential for the sole Creator input write owner."""

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

            def create(value: memoryview) -> EvidenceAcceptanceTransaction:
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
                return build_evidence_acceptance_transaction(
                    conninfo,
                    environment_id=config.environment.environment_id,
                    creator_party_id=creator_party_id,
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


def compose_creator_prompt_service(
    prepared: PreparedEnvironment,
    *,
    creator_party_id: UUID,
    authority_admission: Callable[[], RuntimeFence],
) -> CreatorPromptService:
    """Resolve the Runtime credential for the T-04 Creator Prompt owner."""

    locator = prepared.effective.config.secret_locators.get(RUNTIME_LOCATOR_NAME)
    if locator is None:
        raise CreatorPromptViolation("DB-PROMPT-UNAVAILABLE")
    try:
        with prepared.credential_port.resolve(
            locator,
            CredentialPurpose("database.runtime"),
        ) as handle:

            def create(value: memoryview) -> CreatorPromptService:
                try:
                    conninfo = bytes(value).decode("utf-8")
                except UnicodeDecodeError:
                    raise CreatorPromptViolation(
                        "DB-PROMPT-UNAVAILABLE"
                    ) from None
                config = prepared.effective.config
                return build_creator_prompt_service(
                    conninfo,
                    environment_id=config.environment.environment_id,
                    creator_party_id=creator_party_id,
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
                )

            return handle.consume(create)
    except ConfigurationViolation:
        raise CreatorPromptViolation("DB-PROMPT-UNAVAILABLE") from None


def compose_life_opportunity_pipeline(
    prepared: PreparedEnvironment,
    *,
    authority_admission: Callable[[], RuntimeFence],
    wakeups: WorkWakeupBus | None = None,
    notifier: CreatorProjectionNotifier | None = None,
) -> LifeOpportunityPipeline:
    """Resolve the Runtime credential for the P0-S001 source owner."""

    locator = prepared.effective.config.secret_locators.get(RUNTIME_LOCATOR_NAME)
    if locator is None:
        raise LifeViolation("LIFE-DATABASE")
    try:
        with prepared.credential_port.resolve(
            locator,
            CredentialPurpose("database.runtime"),
        ) as handle:

            def create(value: memoryview) -> LifeOpportunityPipeline:
                try:
                    conninfo = bytes(value).decode("utf-8")
                except UnicodeDecodeError:
                    raise LifeViolation("LIFE-DATABASE") from None
                config = prepared.effective.config
                return build_life_opportunity_pipeline(
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
    wakeups: WorkWakeupBus | None = None,
    diagnostic: Callable[[str], None] | None = None,
) -> ContextPipeline:
    """Resolve the Runtime credential for the active S023 selector and worker."""

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

            def create(value: memoryview) -> ContextPipeline:
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
                return build_context_pipeline(
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
                    policy_digest=Digest.from_bytes(
                        CONTEXT_POLICY_VERSION.encode("ascii")
                    ),
                    web_search_active=prepared.composition.web_search_active,
                    wakeups=wakeups,
                    diagnostic=diagnostic,
                )

            return handle.consume(create)
    except ConfigurationViolation:
        raise DatabaseViolation(
            "DB-ROLE-CREDENTIAL-SCOPE",
            "the configured PostgreSQL connection is unavailable",
            status="unavailable",
            exit_code=3,
        ) from None


def compose_model_pipeline(
    prepared: PreparedEnvironment,
    *,
    authority_admission: Callable[[], RuntimeFence],
    wakeups: WorkWakeupBus | None = None,
    diagnostic: Callable[[str], None] | None = None,
) -> ModelPipeline:
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

            def create(value: memoryview) -> ModelPipeline:
                try:
                    conninfo = bytes(value).decode("utf-8")
                except UnicodeDecodeError:
                    raise ModelViolation("MODEL-DATABASE") from None
                config = prepared.effective.config
                return build_model_pipeline(
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
                    credential_port=prepared.credential_port,
                    credential_locator=model_locator,
                    web_search_active=prepared.composition.web_search_active,
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
    diagnostic: Callable[[str], None] | None = None,
) -> WebSearchPipeline:
    """Resolve the fixed database and Ark credentials for S033 custody."""

    database_locator = prepared.effective.config.secret_locators.get(
        RUNTIME_LOCATOR_NAME
    )
    model_locator = prepared.effective.config.secret_locators.get(MODEL_LOCATOR_NAME)
    if database_locator is None or model_locator is None:
        raise WebObservationViolation("WEB-CREDENTIAL")
    try:
        manifest_bytes = (
            files("armi_runtime.composition.runtime_resources")
            .joinpath("web-search-custody.manifest.json")
            .read_bytes()
        )
    except OSError:
        raise WebObservationViolation("WEB-MANIFEST") from None
    try:
        with prepared.credential_port.resolve(
            database_locator,
            CredentialPurpose("database.runtime"),
        ) as handle:

            def create(value: memoryview) -> WebSearchPipeline:
                try:
                    conninfo = bytes(value).decode("utf-8")
                except UnicodeDecodeError:
                    raise WebObservationViolation("WEB-DATABASE") from None
                config = prepared.effective.config
                return build_web_search_pipeline(
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
                    credential_port=prepared.credential_port,
                    credential_locator=model_locator,
                    manifest_bytes=manifest_bytes,
                    diagnostic=diagnostic,
                )

            return handle.consume(create)
    except ConfigurationViolation:
        raise WebObservationViolation("WEB-CREDENTIAL") from None


def compose_web_research_admission_pipeline(
    prepared: PreparedEnvironment,
    *,
    authority_admission: Callable[[], RuntimeFence],
    custody: WebSearchPipeline,
    diagnostic: Callable[[str], None] | None = None,
) -> WebResearchAdmissionPipeline:
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

            def create(value: memoryview) -> WebResearchAdmissionPipeline:
                try:
                    conninfo = bytes(value).decode("utf-8")
                except UnicodeDecodeError:
                    raise WebResearchViolation("WEB-RESEARCH-DATABASE") from None
                config = prepared.effective.config
                return build_web_research_admission_pipeline(
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
                    custody=custody,
                    diagnostic=diagnostic,
                )

            return handle.consume(create)
    except ConfigurationViolation:
        raise WebResearchViolation("WEB-RESEARCH-DATABASE") from None


def compose_candidate_validation_pipeline(
    prepared: PreparedEnvironment,
    *,
    authority_admission: Callable[[], RuntimeFence],
    wakeups: WorkWakeupBus | None = None,
    diagnostic: Callable[[str], None] | None = None,
) -> CandidateValidationPipeline:
    """Resolve the Runtime credential for the active S025 validator."""

    locator = prepared.effective.config.secret_locators.get(RUNTIME_LOCATOR_NAME)
    if locator is None:
        raise CandidateViolation("CANDIDATE-DATABASE")
    try:
        with prepared.credential_port.resolve(
            locator,
            CredentialPurpose("database.runtime"),
        ) as handle:

            def create(value: memoryview) -> CandidateValidationPipeline:
                try:
                    conninfo = bytes(value).decode("utf-8")
                except UnicodeDecodeError:
                    raise CandidateViolation("CANDIDATE-DATABASE") from None
                config = prepared.effective.config
                return build_candidate_validation_pipeline(
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
                    policy_digest=Digest.from_bytes(
                        CANDIDATE_POLICY_VERSION.encode("ascii")
                    ),
                    web_search_active=prepared.composition.web_search_active,
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
                    notifier=notifier,
                    wakeups=wakeups,
                    diagnostic=diagnostic,
                    fault_injector=fault_injector,
                )

            return handle.consume(create)
    except ConfigurationViolation:
        raise SubjectCommitViolation("SUBJECT-DATABASE") from None


def compose_capability_policy(
    prepared: PreparedEnvironment,
    *,
    authority_admission: Callable[[], RuntimeFence],
    cursor_key: bytes,
    notifier: CreatorProjectionNotifier | None = None,
) -> PostgreSQLCreatorGrantPolicy:
    """Resolve the Runtime credential for the sole active T-04 policy."""

    locator = prepared.effective.config.secret_locators.get(RUNTIME_LOCATOR_NAME)
    if locator is None:
        raise CapabilityViolation("POLICY-DATABASE")
    try:
        with prepared.credential_port.resolve(
            locator, CredentialPurpose("database.runtime")
        ) as handle:

            def create(value: memoryview) -> PostgreSQLCreatorGrantPolicy:
                try:
                    conninfo = bytes(value).decode("utf-8")
                except UnicodeDecodeError:
                    raise CapabilityViolation("POLICY-DATABASE") from None
                config = prepared.effective.config
                return PostgreSQLCreatorGrantPolicy(
                    conninfo,
                    environment_id=config.environment.environment_id,
                    pool_min=config.database.pool_min,
                    pool_max=config.database.pool_max,
                    acquire_timeout_seconds=config.database.pool_acquire_timeout_seconds,
                    statement_timeout_seconds=config.database.statement_timeout_seconds,
                    authority_admission=authority_admission,
                    cursor_key=cursor_key,
                    notifier=notifier,
                )

            return handle.consume(create)
    except ConfigurationViolation:
        raise CapabilityViolation("POLICY-DATABASE") from None


def compose_response_admission_pipeline(
    prepared: PreparedEnvironment,
    *,
    authority_admission: Callable[[], RuntimeFence],
    wakeups: WorkWakeupBus | None = None,
    diagnostic: Callable[[str], None] | None = None,
) -> ResponseAdmissionPipeline:
    """Resolve the Runtime credential for the S028 admission worker."""

    locator = prepared.effective.config.secret_locators.get(RUNTIME_LOCATOR_NAME)
    if locator is None:
        raise ResponseViolation("RESPONSE-DATABASE")
    try:
        with prepared.credential_port.resolve(
            locator, CredentialPurpose("database.runtime")
        ) as handle:

            def create(value: memoryview) -> ResponseAdmissionPipeline:
                try:
                    conninfo = bytes(value).decode("utf-8")
                except UnicodeDecodeError:
                    raise ResponseViolation("RESPONSE-DATABASE") from None
                config = prepared.effective.config
                return build_response_admission_pipeline(
                    conninfo,
                    environment_id=config.environment.environment_id,
                    data_root=prepared.data_root,
                    max_object_bytes=config.artifacts.max_object_bytes,
                    pool_min=config.database.pool_min,
                    pool_max=config.database.pool_max,
                    acquire_timeout_seconds=config.database.pool_acquire_timeout_seconds,
                    statement_timeout_seconds=config.database.statement_timeout_seconds,
                    authority_admission=authority_admission,
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
) -> PostgreSQLRuntimeRecovery:
    """Resolve the Runtime credential for the fenced startup recovery gateway."""

    if not callable(authority_admission):
        raise TypeError("authority_admission must be callable")
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
    notifier: CreatorProjectionNotifier | None = None,
    wakeups: WorkWakeupBus | None = None,
    diagnostic: Callable[[str], None] | None = None,
    fault_injector: Callable[[str], None] | None = None,
) -> EffectRegistrationPipeline:
    """Resolve the Runtime credential for the S029 T-05 worker."""

    from armi_kernel.application import EffectViolation

    locator = prepared.effective.config.secret_locators.get(RUNTIME_LOCATOR_NAME)
    if locator is None:
        raise EffectViolation("EFFECT-DATABASE")
    try:
        with prepared.credential_port.resolve(
            locator, CredentialPurpose("database.runtime")
        ) as handle:

            def create(value: memoryview) -> EffectRegistrationPipeline:
                try:
                    conninfo = bytes(value).decode("utf-8")
                except UnicodeDecodeError:
                    raise EffectViolation("EFFECT-DATABASE") from None
                config = prepared.effective.config
                return build_effect_registration_pipeline(
                    conninfo,
                    environment_id=config.environment.environment_id,
                    data_root=prepared.data_root,
                    max_object_bytes=config.artifacts.max_object_bytes,
                    pool_min=config.database.pool_min,
                    pool_max=config.database.pool_max,
                    acquire_timeout_seconds=config.database.pool_acquire_timeout_seconds,
                    statement_timeout_seconds=config.database.statement_timeout_seconds,
                    authority_admission=authority_admission,
                    notifier=notifier,
                    wakeups=wakeups,
                    diagnostic=diagnostic,
                    fault_injector=fault_injector,
                )

            return handle.consume(create)
    except ConfigurationViolation:
        raise EffectViolation("EFFECT-DATABASE") from None


def compose_codex_pipeline(
    prepared: PreparedEnvironment,
    *,
    creator_party_id: UUID,
    authority_admission: Callable[[], RuntimeFence],
    notifier: CreatorProjectionNotifier | None = None,
    diagnostic: Callable[[str], None] | None = None,
) -> CodexEffectPipeline:
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

            def create(value: memoryview) -> CodexEffectPipeline:
                try:
                    conninfo = bytes(value).decode("utf-8")
                except UnicodeDecodeError:
                    raise CodexDelegationViolation(
                        "CODEX-DELEGATION-DATABASE"
                    ) from None
                config = prepared.effective.config

                async def reject_dynamic_lock(
                    connection: object, target: object
                ) -> None:
                    del connection, target
                    raise CodexDelegationViolation("CODEX-DELEGATION-LOCK")

                factory = PostgreSQLUnitOfWorkFactory(
                    conninfo,
                    environment_id=config.environment.environment_id,
                    lock_acquirer=reject_dynamic_lock,
                    pool_min=config.database.pool_min,
                    pool_max=config.database.pool_max,
                    acquire_timeout_seconds=config.database.pool_acquire_timeout_seconds,
                    statement_timeout_seconds=config.database.statement_timeout_seconds,
                    authority_admission=authority_admission,
                )
                run_root = prepared.data_root / "codex-runner"
                return CodexEffectPipeline(
                    factory=factory,
                    storage=ContentAddressedArtifactStore(
                        prepared.data_root / "artifacts",
                        max_object_bytes=config.artifacts.max_object_bytes,
                    ),
                    environment_root=prepared.root,
                    run_root=run_root,
                    creator_party_id=creator_party_id,
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
    "compose_candidate_validation_pipeline",
    "compose_capability_policy",
    "compose_codex_pipeline",
    "compose_context_pipeline",
    "compose_creator_activity_query",
    "compose_creator_input",
    "compose_creator_maintenance_query",
    "compose_creator_prompt_service",
    "compose_creator_relationship_query",
    "compose_effect_registration_pipeline",
    "compose_exact_life_query_pipeline",
    "compose_life_opportunity_pipeline",
    "compose_life_record_query",
    "compose_model_pipeline",
    "compose_response_admission_pipeline",
    "compose_runtime_authority",
    "compose_runtime_observation",
    "compose_runtime_recovery",
    "compose_scene_timeline_query",
    "compose_subject_commit_pipeline",
    "compose_web_research_admission_pipeline",
    "compose_web_search_pipeline",
    "inspect_creator_context",
    "inspect_creator_party_id",
    "inspect_operator_schema",
    "inspect_runtime_continuity",
    "inspect_runtime_schema",
    "install_operator_schema",
    "runtime_database_reason",
)
