"""Resolve a paid request's authoritative origin before committing admission."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from armi_attention.api import AutonomyPolicy, AutonomyPort, LifeViolation
from armi_kernel.application import ProviderCallReceipt
from armi_runtime_foundation import (
    PostgreSQLRuntimeUnitOfWork,
    RuntimeTransactionFailure,
)

from armi_runtime.application.opportunity_origin import (
    HUMAN_INPUT_PURPOSES,
    RuntimeOpportunityOrigin,
)


class AutonomyAdmissionFailure(RuntimeTransactionFailure):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class AutonomyRequestAdmission:
    def __init__(
        self,
        owner: AutonomyPort,
        policy: AutonomyPolicy,
        origins: RuntimeOpportunityOrigin,
    ) -> None:
        self._owner = owner
        self._policy = policy
        self._origins = origins

    async def admit(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        receipt: ProviderCallReceipt,
    ) -> None:
        if not receipt.registration or not receipt.billable:
            return
        fence = unit_of_work.runtime_fence
        if fence is None:
            raise AutonomyAdmissionFailure("LIFE-FENCE-REQUIRED")
        # The usage view projects the receipt just written by its owner in this
        # transaction. Neither the model nor the adapter chooses quota attribution.
        rows = await (
            await unit_of_work.transaction.execute(
                """SELECT DISTINCT call.operation_id,call.reference_kind
                   FROM armi.provider_usage_calls AS call
                   WHERE NOT call.legacy AND call.receipt->>'call_id'=%s""",
                (receipt.call_id,),
            )
        ).fetchall()
        if not rows:
            raise AutonomyAdmissionFailure("LIFE-AUTONOMY-CALL-ORIGIN")
        # Voice and cognition can project the same physical call. Its operation
        # lineage is authoritative; the number of projections is not a call count.
        roots: set[tuple[UUID, str]] = set()
        for operation in {cast(UUID, row[0]) for row in rows if row[0] is not None}:
            roots.add(await self._origins.resolve(unit_of_work.transaction, operation))
        if len(roots) > 1:
            raise AutonomyAdmissionFailure("LIFE-AUTONOMY-CALL-ORIGIN")
        operation_id, root_purpose = next(iter(roots), (None, None))
        if root_purpose in HUMAN_INPUT_PURPOSES:
            return
        if operation_id is None and all(
            row[1] in {"interaction", "voice_session", "voice_turn"} for row in rows
        ):
            return
        try:
            await self._owner.register_request(
                unit_of_work.transaction,
                subject_id=fence.subject_id,
                root_opportunity_id=operation_id,
                call_id=receipt.call_id,
                policy=self._policy,
            )
        except LifeViolation as error:
            raise AutonomyAdmissionFailure(error.code) from None
