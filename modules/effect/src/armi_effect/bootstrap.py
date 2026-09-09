"""Effect module composition entry points."""

from __future__ import annotations

from collections.abc import Callable

from armi_data_rights.api import (
    DataRightsEffectGate,
    DataRightsFencePort,
    DataRightsParticipant,
)
from armi_expression.api import (
    ExpressionEffectRegistrationPort,
    ExpressionIntentReadPort,
)
from armi_interaction.api import InteractionEffectRoutePort
from armi_kernel.application import (
    CreatorProjectionNotifier,
    ExecutionCustodyPort,
    RuntimeFence,
)
from armi_runtime_foundation import (
    PostgreSQLRuntimeUnitOfWorkFactory,
    RecoveryParticipant,
)

from ._admin import PostgreSQLEffectAdmin
from ._application import EffectPipeline
from ._codex_postgresql import PostgreSQLEffectCodexLifecycle
from ._data_rights import PostgreSQLEffectDataRightsParticipant
from ._dispatch import PostgreSQLEffectDispatchRepository
from ._inbox import PostgreSQLLocalInbox
from ._ledger import (
    PostgreSQLDeclaredResponseEffectRegistration,
    PostgreSQLEffectLedgerRepository,
)
from ._read_postgresql import PostgreSQLEffectOperationRead
from ._recovery import EffectRecoveryParticipant
from .api import (
    ActionAdapterPort,
    EffectAdminPort,
    EffectArtifactStorePort,
    EffectCodexArtifactPort,
    EffectCodexLifecyclePort,
    EffectReadPort,
    EffectRuntimePort,
    EffectTimelinePort,
)


def bootstrap_effect_admin() -> EffectAdminPort:
    return PostgreSQLEffectAdmin()


Diagnostic = Callable[[str], None]
FaultInjector = Callable[[str], None]

# Fixed constructors used by the Runtime PostgreSQL integration composition.
# They remain composition-only entry points; consumers never import owner internals.
compose_effect_dispatch_repository = PostgreSQLEffectDispatchRepository
compose_local_inbox = PostgreSQLLocalInbox
compose_effect_ledger_repository = PostgreSQLEffectLedgerRepository


def bootstrap_effect_codex_lifecycle() -> EffectCodexLifecyclePort:
    return PostgreSQLEffectCodexLifecycle()


def bootstrap_expression_effect_registration() -> ExpressionEffectRegistrationPort:
    return PostgreSQLDeclaredResponseEffectRegistration()


def bootstrap_effect_runtime(
    *,
    factory: PostgreSQLRuntimeUnitOfWorkFactory,
    storage: EffectArtifactStorePort,
    intents: ExpressionIntentReadPort,
    codex_artifacts: EffectCodexArtifactPort,
    routes: InteractionEffectRoutePort,
    interaction_delivery: EffectTimelinePort,
    custody: ExecutionCustodyPort,
    data_rights: DataRightsEffectGate,
    data_rights_fence: DataRightsFencePort,
    runtime_admission: Callable[[], RuntimeFence],
    notifier: CreatorProjectionNotifier | None = None,
    diagnostic: Diagnostic | None = None,
    fault_injector: FaultInjector | None = None,
    adapter: ActionAdapterPort | None = None,
    external_message_adapter: ActionAdapterPort | None = None,
    live_voice_adapter: ActionAdapterPort | None = None,
) -> EffectRuntimePort:
    return EffectPipeline(
        factory=factory,
        storage=storage,
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
        adapter=adapter,
        external_message_adapter=external_message_adapter,
        live_voice_adapter=live_voice_adapter,
    )


def bootstrap_effect_data_rights() -> DataRightsParticipant:
    return PostgreSQLEffectDataRightsParticipant()


def bootstrap_effect_recovery() -> RecoveryParticipant:
    return EffectRecoveryParticipant()


def bootstrap_effect_operation_read() -> EffectReadPort:
    return PostgreSQLEffectOperationRead()


__all__ = (
    "bootstrap_effect_admin",
    "bootstrap_effect_codex_lifecycle",
    "bootstrap_effect_data_rights",
    "bootstrap_effect_operation_read",
    "bootstrap_effect_recovery",
    "bootstrap_effect_runtime",
    "bootstrap_expression_effect_registration",
    "compose_effect_dispatch_repository",
    "compose_effect_ledger_repository",
    "compose_local_inbox",
)
