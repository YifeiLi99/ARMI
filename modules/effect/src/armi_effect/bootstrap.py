"""Effect module composition entry points."""

from __future__ import annotations

from collections.abc import Callable

from armi_artifact_store.api import ArtifactCatalogPort
from armi_capability.api import (
    CapabilityActionAuthorizationPort,
    CapabilityAdmissionPort,
    CapabilityDispatchAuthorizationPort,
)
from armi_data_rights.api import DataRightsEffectGate, DataRightsParticipant
from armi_expression.api import (
    ExpressionEffectLinkPort,
    ExpressionEffectRegistrationPort,
    ExpressionIntentReadPort,
    ExpressionResponseAdmissionPort,
)
from armi_interaction.api import InteractionEffectRoutePort
from armi_kernel.application import CreatorProjectionNotifier, DurableWorkPort
from armi_runtime_foundation import (
    PostgreSQLRuntimeUnitOfWorkFactory,
    RecoveryParticipant,
)

from ._admin import PostgreSQLEffectAdmin
from ._application import EffectRegistrationPipeline
from ._codex_postgresql import PostgreSQLEffectCodexLifecycle
from ._data_rights import PostgreSQLEffectDataRightsParticipant
from ._grant import (
    PostgreSQLEffectDispatchBoundary,
    PostgreSQLEffectGrantCancellation,
)
from ._ledger import PostgreSQLDeclaredResponseEffectRegistration
from ._read_postgresql import PostgreSQLEffectOperationRead
from ._recovery import EffectRecoveryParticipant
from ._response import ResponseAdmissionPipeline
from .api import (
    ActionAdapterPort,
    EffectAdminPort,
    EffectArtifactStorePort,
    EffectCodexArtifactPort,
    EffectCodexLifecyclePort,
    EffectDispatchBoundaryPort,
    EffectGrantCancellationPort,
    EffectOperationReadPort,
    EffectRegistrationContextPort,
    EffectRuntimePort,
    EffectTimelinePort,
    EffectWakeupPort,
    ResponseAdmissionRuntimePort,
)


def bootstrap_effect_admin() -> EffectAdminPort:
    return PostgreSQLEffectAdmin()


Diagnostic = Callable[[str], None]
FaultInjector = Callable[[str], None]


def bootstrap_effect_grant_cancellation() -> EffectGrantCancellationPort:
    return PostgreSQLEffectGrantCancellation()


def bootstrap_effect_dispatch_boundary(
    authorization: CapabilityDispatchAuthorizationPort,
) -> EffectDispatchBoundaryPort:
    return PostgreSQLEffectDispatchBoundary(authorization)


def bootstrap_effect_codex_lifecycle(
    authorization: CapabilityDispatchAuthorizationPort,
) -> EffectCodexLifecyclePort:
    return PostgreSQLEffectCodexLifecycle(authorization)


def bootstrap_expression_effect_registration() -> ExpressionEffectRegistrationPort:
    return PostgreSQLDeclaredResponseEffectRegistration()


def bootstrap_effect_runtime(
    *,
    factory: PostgreSQLRuntimeUnitOfWorkFactory,
    storage: EffectArtifactStorePort,
    work: DurableWorkPort,
    authorization: CapabilityActionAuthorizationPort,
    intents: ExpressionIntentReadPort,
    effect_links: ExpressionEffectLinkPort,
    registration_context: EffectRegistrationContextPort,
    codex_artifacts: EffectCodexArtifactPort,
    routes: InteractionEffectRoutePort,
    interaction_delivery: EffectTimelinePort,
    wakeups: EffectWakeupPort,
    notifier: CreatorProjectionNotifier | None = None,
    diagnostic: Diagnostic | None = None,
    fault_injector: FaultInjector | None = None,
    adapter: ActionAdapterPort | None = None,
    external_message_adapter: ActionAdapterPort | None = None,
) -> EffectRuntimePort:
    return EffectRegistrationPipeline(
        factory=factory,
        storage=storage,
        work=work,
        authorization=authorization,
        intents=intents,
        effect_links=effect_links,
        registration_context=registration_context,
        codex_artifacts=codex_artifacts,
        routes=routes,
        interaction_delivery=interaction_delivery,
        wakeups=wakeups,
        notifier=notifier,
        diagnostic=diagnostic,
        fault_injector=fault_injector,
        adapter=adapter,
        external_message_adapter=external_message_adapter,
    )


def bootstrap_response_admission(
    *,
    factory: PostgreSQLRuntimeUnitOfWorkFactory,
    storage: EffectArtifactStorePort,
    work: DurableWorkPort,
    artifacts: ArtifactCatalogPort,
    capability: CapabilityAdmissionPort,
    data_rights: DataRightsEffectGate,
    expression: ExpressionResponseAdmissionPort,
    wakeups: EffectWakeupPort,
    diagnostic: Diagnostic | None = None,
) -> ResponseAdmissionRuntimePort:
    return ResponseAdmissionPipeline(
        factory=factory,
        storage=storage,
        work=work,
        artifacts=artifacts,
        capability=capability,
        data_rights=data_rights,
        expression=expression,
        wakeups=wakeups,
        diagnostic=diagnostic,
    )


def bootstrap_effect_data_rights() -> DataRightsParticipant:
    return PostgreSQLEffectDataRightsParticipant()


def bootstrap_effect_recovery() -> RecoveryParticipant:
    return EffectRecoveryParticipant()


def bootstrap_effect_operation_read() -> EffectOperationReadPort:
    return PostgreSQLEffectOperationRead()


__all__ = (
    "bootstrap_effect_admin",
    "bootstrap_effect_codex_lifecycle",
    "bootstrap_effect_data_rights",
    "bootstrap_effect_dispatch_boundary",
    "bootstrap_effect_grant_cancellation",
    "bootstrap_effect_operation_read",
    "bootstrap_effect_recovery",
    "bootstrap_effect_runtime",
    "bootstrap_expression_effect_registration",
    "bootstrap_response_admission",
)
