"""Explicit database composition for Runtime probing and operator migration."""

from __future__ import annotations

from collections.abc import Callable
from importlib.resources import files
from typing import Final
from uuid import UUID

from armi_kernel.application import (
    CandidateViolation,
    CapabilityViolation,
    ContextViolation,
    CreatorProjectionNotifier,
    CredentialPort,
    CredentialPurpose,
    ModelViolation,
    ResponseViolation,
    RuntimeFence,
    SubjectCommitViolation,
)
from armi_kernel.contracts import Digest

from armi_runtime.adapters.creator_identity import CreatorContext, read_creator_context
from armi_runtime.adapters.persistence.birth import (
    ContinuityState,
    probe_continuity,
)
from armi_runtime.adapters.persistence.capability_policy import (
    PostgreSQLCreatorGrantPolicy,
)
from armi_runtime.adapters.persistence.recovery import (
    PostgreSQLRuntimeRecovery,
)
from armi_runtime.adapters.persistence.runtime_authority import (
    PostgreSQLRuntimeAuthority,
)
from armi_runtime.adapters.persistence.scene_timeline import (
    PostgreSQLSceneTimelineQuery,
)
from armi_runtime.adapters.persistence.schema_gateway import (
    DatabaseViolation,
    PostgreSQLSchemaGateway,
    SchemaStatus,
)

from .birth_manifest import packaged_birth_digests
from .candidate_pipeline import (
    CandidateValidationPipeline,
    build_candidate_validation_pipeline,
)
from .configuration import ConfigurationViolation
from .context_pipeline import ContextPipeline, build_context_pipeline
from .creator_input import (
    EvidenceAcceptanceTransaction,
    build_evidence_acceptance_transaction,
)
from .effect_pipeline import (
    EffectRegistrationPipeline,
    build_effect_registration_pipeline,
)
from .environment import PreparedEnvironment
from .model_pipeline import ModelPipeline, build_model_pipeline
from .response_pipeline import (
    ResponseAdmissionPipeline,
    build_response_admission_pipeline,
)
from .subject_commit_pipeline import (
    SubjectCommitPipeline,
    build_subject_commit_pipeline,
)

RUNTIME_LOCATOR_NAME: Final = "database.runtime"
MIGRATOR_LOCATOR_NAME: Final = "database.migrator"
MODEL_LOCATOR_NAME: Final = "model.ark_api_key"

_REASON_BY_CODE: Final = {
    "DB-CONNECTION-UNAVAILABLE": "RUNTIME_DATABASE_UNAVAILABLE",
    "DB-PG-VERSION": "RUNTIME_DATABASE_VERSION_MISMATCH",
    "DB-DATABASE-IDENTITY": "RUNTIME_DATABASE_IDENTITY_MISMATCH",
    "DB-RUNTIME-ROLE-UNSAFE": "RUNTIME_DATABASE_ROLE_UNSAFE",
    "DB-SCHEMA-MISSING": "RUNTIME_SCHEMA_MISSING",
    "DB-SCHEMA-AHEAD": "RUNTIME_SCHEMA_AHEAD",
    "DB-SCHEMA-GAP": "RUNTIME_SCHEMA_INVALID",
    "DB-SCHEMA-HASH": "RUNTIME_SCHEMA_INVALID",
    "DB-SCHEMA-DIRTY": "RUNTIME_SCHEMA_INVALID",
    "DB-SCHEMA-INVARIANT": "RUNTIME_SCHEMA_INVALID",
    "DB-MANIFEST-DRIFT": "RUNTIME_SCHEMA_INVALID",
    "DB-ROLE-MANIFEST-DRIFT": "RUNTIME_DATABASE_ROLE_POLICY_INVALID",
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
                if operation == "upgrade":
                    return gateway.upgrade(
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
    """Read-only Runtime probe; this path cannot invoke schema upgrade."""

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


def upgrade_operator_schema(prepared: PreparedEnvironment) -> SchemaStatus:
    return _with_connection(
        prepared,
        locator_name=MIGRATOR_LOCATOR_NAME,
        purpose="database.migrator",
        operation="upgrade",
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
                    schema_manifest_digest=digests["schema_manifest_digest"],
                    birth_contract_digest=digests["birth_contract_digest"],
                    creator_asset_digest=digests["creator_asset_manifest_digest"],
                )

            return handle.consume(invoke)
    except ConfigurationViolation:
        return ContinuityState.INVALID


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
    diagnostic: Callable[[str], None] | None = None,
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


def compose_context_pipeline(
    prepared: PreparedEnvironment,
    *,
    authority_admission: Callable[[], RuntimeFence],
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
        policy = (
            files("armi_runtime.composition.runtime_resources")
            .joinpath("context-policy.manifest.json")
            .read_bytes()
        )
    except OSError:
        raise ContextViolation("CTX-POLICY-MISSING") from None
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
                    policy_digest=Digest.from_bytes(policy),
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
                    diagnostic=diagnostic,
                )

            return handle.consume(create)
    except ConfigurationViolation:
        raise ModelViolation("MODEL-CREDENTIAL") from None


def compose_candidate_validation_pipeline(
    prepared: PreparedEnvironment,
    *,
    authority_admission: Callable[[], RuntimeFence],
    diagnostic: Callable[[str], None] | None = None,
) -> CandidateValidationPipeline:
    """Resolve the Runtime credential for the active S025 validator."""

    locator = prepared.effective.config.secret_locators.get(RUNTIME_LOCATOR_NAME)
    if locator is None:
        raise CandidateViolation("CANDIDATE-DATABASE")
    try:
        policy = (
            files("armi_runtime.composition.runtime_resources")
            .joinpath("candidate-validation-policy.manifest.json")
            .read_bytes()
        )
    except OSError:
        raise CandidateViolation("CANDIDATE-POLICY-MISSING") from None
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
                    policy_digest=Digest.from_bytes(policy),
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
    diagnostic: Callable[[str], None] | None = None,
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
                    diagnostic=diagnostic,
                )

            return handle.consume(create)
    except ConfigurationViolation:
        raise SubjectCommitViolation("SUBJECT-DATABASE") from None


def compose_capability_policy(
    prepared: PreparedEnvironment,
    *,
    authority_admission: Callable[[], RuntimeFence],
    cursor_key: bytes,
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
                )

            return handle.consume(create)
    except ConfigurationViolation:
        raise CapabilityViolation("POLICY-DATABASE") from None


def compose_response_admission_pipeline(
    prepared: PreparedEnvironment,
    *,
    authority_admission: Callable[[], RuntimeFence],
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
    diagnostic: Callable[[str], None] | None = None,
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
                    diagnostic=diagnostic,
                )

            return handle.consume(create)
    except ConfigurationViolation:
        raise EffectViolation("EFFECT-DATABASE") from None


__all__ = (
    "MIGRATOR_LOCATOR_NAME",
    "RUNTIME_LOCATOR_NAME",
    "ContinuityState",
    "DatabaseViolation",
    "compose_candidate_validation_pipeline",
    "compose_capability_policy",
    "compose_context_pipeline",
    "compose_creator_input",
    "compose_effect_registration_pipeline",
    "compose_model_pipeline",
    "compose_response_admission_pipeline",
    "compose_runtime_authority",
    "compose_runtime_recovery",
    "compose_scene_timeline_query",
    "compose_subject_commit_pipeline",
    "inspect_creator_context",
    "inspect_creator_party_id",
    "inspect_operator_schema",
    "inspect_runtime_continuity",
    "inspect_runtime_schema",
    "runtime_database_reason",
    "upgrade_operator_schema",
)
