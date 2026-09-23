"""Stable, business-neutral Runtime integration contracts."""

from .admin_content import (
    AdminContentArtifactPort,
    AdminContentCommand,
    AdminContentContext,
    AdminContentGuardPort,
    AdminContentPort,
    AdminContentViolation,
)
from .admin_transactions import (
    PostgreSQLAdminParameter,
    PostgreSQLAdminResult,
    PostgreSQLAdminScalar,
    PostgreSQLAdminTransaction,
    PostgreSQLAdminUnitOfWork,
    PostgreSQLAdminUnitOfWorkFactory,
)
from .autonomy_query import autonomy_result, autonomy_statement
from .cognition_guard import cancel_cognition_work, subject_context_current
from .diagnostic_bootstrap import bootstrap_diagnostics
from .diagnostic_log import DiagnosticLog, DiagnosticSinkStatus
from .diagnostic_query import DiagnosticQuery
from .diagnostic_redaction import exception_evidence, redact, safe_text
from .diagnostic_stream import DiagnosticTextStream
from .projection_cursor import (
    ProjectionCursorCodec,
    ProjectionCursorInvalid,
    ProjectionCursorPage,
    ProjectionCursorStale,
)
from .provider_usage_query import usage_result, usage_statement
from .recovery import (
    EmptyRecoveryParticipant,
    InterruptedWorkEndParticipant,
    OwnerReconciliationContext,
    RecoveryAuditContribution,
    RecoveryContribution,
    RecoveryDependentParticipant,
    RecoveryFindingContribution,
    RecoveryFindingDecision,
    RecoveryMetricContribution,
    RecoveryOwnerIdentity,
    RecoveryParticipant,
    RecoveryScope,
    RecoveryWorkSnapshot,
)
from .transactions import (
    PostgreSQLParameter,
    PostgreSQLParameters,
    PostgreSQLResult,
    PostgreSQLRuntimeUnitOfWork,
    PostgreSQLRuntimeUnitOfWorkContext,
    PostgreSQLRuntimeUnitOfWorkFactory,
    PostgreSQLScalar,
    PostgreSQLTransaction,
    PostgreSQLTransactionAccess,
    RuntimeTransactionFailure,
    StopSignal,
)

__all__ = (
    "AdminContentArtifactPort",
    "AdminContentCommand",
    "AdminContentContext",
    "AdminContentGuardPort",
    "AdminContentPort",
    "AdminContentViolation",
    "DiagnosticLog",
    "DiagnosticQuery",
    "DiagnosticSinkStatus",
    "DiagnosticTextStream",
    "EmptyRecoveryParticipant",
    "InterruptedWorkEndParticipant",
    "OwnerReconciliationContext",
    "PostgreSQLAdminParameter",
    "PostgreSQLAdminResult",
    "PostgreSQLAdminScalar",
    "PostgreSQLAdminTransaction",
    "PostgreSQLAdminUnitOfWork",
    "PostgreSQLAdminUnitOfWorkFactory",
    "PostgreSQLParameter",
    "PostgreSQLParameters",
    "PostgreSQLResult",
    "PostgreSQLRuntimeUnitOfWork",
    "PostgreSQLRuntimeUnitOfWorkContext",
    "PostgreSQLRuntimeUnitOfWorkFactory",
    "PostgreSQLScalar",
    "PostgreSQLTransaction",
    "PostgreSQLTransactionAccess",
    "ProjectionCursorCodec",
    "ProjectionCursorInvalid",
    "ProjectionCursorPage",
    "ProjectionCursorStale",
    "RecoveryAuditContribution",
    "RecoveryContribution",
    "RecoveryDependentParticipant",
    "RecoveryFindingContribution",
    "RecoveryFindingDecision",
    "RecoveryMetricContribution",
    "RecoveryOwnerIdentity",
    "RecoveryParticipant",
    "RecoveryScope",
    "RecoveryWorkSnapshot",
    "RuntimeTransactionFailure",
    "StopSignal",
    "autonomy_result",
    "autonomy_statement",
    "bootstrap_diagnostics",
    "cancel_cognition_work",
    "exception_evidence",
    "redact",
    "safe_text",
    "subject_context_current",
    "usage_result",
    "usage_statement",
)
