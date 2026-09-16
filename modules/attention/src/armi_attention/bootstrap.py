"""Composition-only construction of the active Attention module."""

from __future__ import annotations

from armi_activity.api import ActivityReadPort
from armi_data_rights.api import DataRightsParticipant
from armi_kernel.application import CreatorProjectionNotifier
from armi_runtime_foundation import (
    PostgreSQLRuntimeUnitOfWorkFactory,
    RecoveryParticipant,
)
from armi_sleep.api import SleepMaintenancePort, SleepOpportunityPort, SleepReadPort
from armi_subject_state.api import SubjectStateReadPort

from ._admin import PostgreSQLOpportunityAdmin
from ._application import compose_opportunity_pipeline
from ._autonomy_postgresql import PostgreSQLAutonomyOwner
from ._data_rights import PostgreSQLOpportunityDataRightsParticipant
from ._owner import PostgreSQLOpportunityOwner
from ._recovery import OpportunityRecoveryParticipant
from .api import (
    AutonomyPolicy,
    AutonomyPort,
    LifeOpportunityFactsPort,
    OpportunityAdminPort,
    OpportunityAdmissionPort,
    OpportunityCognitionPort,
    OpportunityOwnerPort,
    OpportunityRuntimePort,
    OpportunityTransitionPort,
    OpportunityWakeupPort,
)


def bootstrap_autonomy() -> AutonomyPort:
    return PostgreSQLAutonomyOwner()


def bootstrap_opportunity_admin() -> OpportunityAdminPort:
    return PostgreSQLOpportunityAdmin()


def bootstrap_opportunity_owner(
    autonomy_policy: AutonomyPolicy | None = None,
) -> OpportunityOwnerPort:
    return PostgreSQLOpportunityOwner(autonomy_policy)


def bootstrap_opportunity_admission() -> OpportunityAdmissionPort:
    return PostgreSQLOpportunityOwner()


def bootstrap_opportunity_sleep() -> SleepOpportunityPort:
    return PostgreSQLOpportunityOwner()


def bootstrap_opportunity_transition() -> OpportunityTransitionPort:
    return PostgreSQLOpportunityOwner()


def bootstrap_opportunity_cognition() -> OpportunityCognitionPort:
    return PostgreSQLOpportunityOwner()


def bootstrap_opportunity(
    *,
    factory: PostgreSQLRuntimeUnitOfWorkFactory,
    facts: LifeOpportunityFactsPort,
    activity_read: ActivityReadPort,
    sleep_maintenance: SleepMaintenancePort,
    sleep_read: SleepReadPort,
    subject_state_read: SubjectStateReadPort,
    wakeups: OpportunityWakeupPort | None = None,
    model_concurrency: int = 2,
    maintenance_consideration_seconds: int = 57_600,
    maintenance_deadline_seconds: int = 86_400,
    notifier: CreatorProjectionNotifier | None = None,
    autonomy_policy: AutonomyPolicy | None = None,
) -> OpportunityRuntimePort:
    return compose_opportunity_pipeline(
        autonomy_policy=autonomy_policy,
        factory=factory,
        facts=facts,
        activity_read=activity_read,
        sleep_maintenance=sleep_maintenance,
        sleep_read=sleep_read,
        subject_state_read=subject_state_read,
        wakeups=wakeups,
        model_concurrency=model_concurrency,
        maintenance_consideration_seconds=maintenance_consideration_seconds,
        maintenance_deadline_seconds=maintenance_deadline_seconds,
        notifier=notifier,
    )


def bootstrap_opportunity_data_rights() -> DataRightsParticipant:
    return PostgreSQLOpportunityDataRightsParticipant()


def bootstrap_opportunity_recovery() -> RecoveryParticipant:
    return OpportunityRecoveryParticipant()


__all__ = (
    "bootstrap_autonomy",
    "bootstrap_opportunity",
    "bootstrap_opportunity_admin",
    "bootstrap_opportunity_admission",
    "bootstrap_opportunity_cognition",
    "bootstrap_opportunity_data_rights",
    "bootstrap_opportunity_owner",
    "bootstrap_opportunity_recovery",
    "bootstrap_opportunity_sleep",
    "bootstrap_opportunity_transition",
)
