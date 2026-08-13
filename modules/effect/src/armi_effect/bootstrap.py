"""Effect module composition entry points."""

from __future__ import annotations

from collections.abc import Callable

from armi_capability.api import CapabilityGrantConsumptionPort
from armi_expression.api import ExpressionEffectRegistrationPort
from armi_kernel.application import CreatorProjectionNotifier, DurableWorkPort
from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWorkFactory

from ._application import EffectRegistrationPipeline
from ._grant import (
    PostgreSQLEffectDispatchBoundary,
    PostgreSQLEffectGrantCancellation,
)
from ._ledger import PostgreSQLDeclaredResponseEffectRegistration
from ._response import ResponseAdmissionPipeline
from .api import (
    ActionAdapterPort,
    EffectArtifactStorePort,
    EffectDispatchBoundaryPort,
    EffectGrantCancellationPort,
    EffectRuntimePort,
    EffectTimelinePort,
    EffectWakeupPort,
    ResponseAdmissionRuntimePort,
)

Diagnostic = Callable[[str], None]
FaultInjector = Callable[[str], None]


def bootstrap_effect_grant_cancellation() -> EffectGrantCancellationPort:
    return PostgreSQLEffectGrantCancellation()


def bootstrap_effect_dispatch_boundary() -> EffectDispatchBoundaryPort:
    return PostgreSQLEffectDispatchBoundary()


def bootstrap_expression_effect_registration() -> ExpressionEffectRegistrationPort:
    return PostgreSQLDeclaredResponseEffectRegistration()


def bootstrap_effect_runtime(
    *,
    factory: PostgreSQLRuntimeUnitOfWorkFactory,
    storage: EffectArtifactStorePort,
    work: DurableWorkPort,
    capability_consumption: CapabilityGrantConsumptionPort,
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
        capability_consumption=capability_consumption,
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
    wakeups: EffectWakeupPort,
    diagnostic: Diagnostic | None = None,
) -> ResponseAdmissionRuntimePort:
    return ResponseAdmissionPipeline(
        factory=factory,
        storage=storage,
        work=work,
        wakeups=wakeups,
        diagnostic=diagnostic,
    )


__all__ = (
    "bootstrap_effect_dispatch_boundary",
    "bootstrap_effect_grant_cancellation",
    "bootstrap_effect_runtime",
    "bootstrap_expression_effect_registration",
    "bootstrap_response_admission",
)
