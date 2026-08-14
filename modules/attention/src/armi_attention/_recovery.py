"""Attention-owned startup recovery contribution."""

from armi_runtime_foundation import (
    PostgreSQLTransaction,
    RecoveryContribution,
    RecoveryFindingContribution,
    RecoveryFindingDecision,
    RecoveryMetricContribution,
    RecoveryOwnerIdentity,
    RecoveryScope,
    RecoveryWorkSnapshot,
)


class OpportunityRecoveryParticipant:
    owner_identity = RecoveryOwnerIdentity("opportunity")
    work_scopes: tuple[tuple[str, str], ...] = ()

    async def recover(
        self,
        transaction: PostgreSQLTransaction,
        scope: RecoveryScope,
        work: tuple[RecoveryWorkSnapshot, ...],
    ) -> RecoveryContribution:
        return await self.recover_with_prior(transaction, scope, work, ())

    async def recover_with_prior(
        self,
        transaction: PostgreSQLTransaction,
        scope: RecoveryScope,
        work: tuple[RecoveryWorkSnapshot, ...],
        prior: tuple[RecoveryContribution, ...],
    ) -> RecoveryContribution:
        del work
        terminal = tuple(
            finding
            for contribution in prior
            if contribution.owner.value == "cognition"
            for finding in contribution.findings
            if finding.reference is not None
            and finding.kind
            in {"opportunity_terminal_cancelled", "opportunity_terminal_resolved"}
        )
        repaired: list[RecoveryFindingContribution] = []
        for finding in terminal:
            disposition = (
                "cancelled"
                if finding.kind == "opportunity_terminal_cancelled"
                else "resolved"
            )
            row = await (
                await transaction.execute(
                    """
                    UPDATE armi.opportunities
                    SET current_disposition = %s,
                        resolved_at = statement_timestamp()
                    WHERE opportunity_id = %s
                      AND current_disposition = 'selected'
                    RETURNING opportunity_id
                    """,
                    (disposition, finding.reference),
                )
            ).fetchone()
            if row is not None:
                repaired.append(
                    RecoveryFindingContribution(
                        "opportunity",
                        RecoveryFindingDecision.TERMINAL,
                        (
                            "REC-OPPORTUNITY-COGNITION-CANCELLED"
                            if disposition == "cancelled"
                            else "REC-OPPORTUNITY-COGNITION-RESOLVED"
                        ),
                        row[0],
                    )
                )
        row = await (
            await transaction.execute(
                """
            SELECT count(*) FROM armi.opportunities
            WHERE subject_id=%s AND current_disposition IN ('open','selected')
              AND (expires_at IS NULL OR expires_at>statement_timestamp())
        """,
                (scope.subject_id,),
            )
        ).fetchone()
        return RecoveryContribution(
            self.owner_identity,
            findings=tuple(repaired),
            metrics=(
                RecoveryMetricContribution(
                    "opportunity.resumable_count", int(row[0]) if row else 0
                ),
            ),
        )
