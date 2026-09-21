"""A maintenance stage accepts one result and rejects an unavailable target."""

from datetime import UTC, datetime
from typing import cast
from unittest.mock import AsyncMock
from uuid import uuid7

import pytest
from armi_runtime_foundation import PostgreSQLTransaction
from armi_sleep._application import SleepApplication
from armi_sleep._commit import PostgreSQLSleepCommit
from armi_sleep.api import (
    CandidateMaintenanceDecisionDraft,
    MaintenancePhase,
    MaintenanceWorkOutcome,
    SleepCommitContext,
    SleepViolation,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("target_exists", [True, False])
async def test_phase_result_requires_an_unfinished_target(target_exists: bool) -> None:
    revision_id = uuid7()
    context = SleepCommitContext(
        uuid7(),
        uuid7(),
        uuid7(),
        uuid7(),
        0,
        uuid7(),
        uuid7(),
        "perform_subject_self_check",
        "maintenance_phase_revision",
        revision_id,
        2,
        0,
        datetime.now(UTC),
        None,
    )
    decision = CandidateMaintenanceDecisionDraft(
        "proposal:1",
        "group:1",
        (1,),
        uuid7(),
        revision_id,
        2,
        MaintenancePhase.SELF_CHECK,
        MaintenanceWorkOutcome.NO_ISSUE,
        "检查完成,未发现问题。",
    )
    transaction = AsyncMock()
    transaction.execute.return_value.fetchone.return_value = (
        (revision_id,) if target_exists else None
    )
    commit = PostgreSQLSleepCommit(SleepApplication())
    pending = commit.commit(
        cast(PostgreSQLTransaction, transaction),
        context=context,
        application_id=uuid7(),
        commit_id=uuid7(),
        resulting_subject_version=1,
        drafts=(decision,),
    )
    if target_exists:
        await pending
    else:
        with pytest.raises(SleepViolation, match="SLEEP-MAINTENANCE-COMMIT"):
            await pending
