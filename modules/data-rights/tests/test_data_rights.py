from __future__ import annotations

import asyncio
import inspect
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock
from uuid import uuid7

import pytest
from armi_data_rights._application import DataRightsOrderService
from armi_data_rights._deletion import LocalDataDeletionExecutor
from armi_data_rights._deletion_postgresql import LocalDataDeletionRepository
from armi_data_rights._postgresql import (
    DataRightsOrderRepository,
    DataRightsOrderSnapshot,
)
from armi_data_rights.api import (
    DataRightsDeletionPreview,
    DataRightsExecutionStatus,
    DataRightsOrderCommand,
    DataRightsOrderKind,
    DataRightsOrderResult,
    DataRightsRequesterKind,
    DataRightsScopeKind,
    DataRightsViolation,
)
from armi_data_rights.bootstrap import bootstrap_data_rights_core
from armi_kernel.contracts import Digest, IdempotencyKey, Instant, TraceId
from armi_runtime_foundation import (
    PostgreSQLRuntimeUnitOfWork,
    RuntimeTransactionFailure,
)


class _Cursor:
    def __init__(self, row: tuple[object, ...] | None) -> None:
        self._row = row

    async def fetchone(self) -> tuple[object, ...] | None:
        return self._row


class _Connection:
    def __init__(self, blocked: bool) -> None:
        self.blocked = blocked
        self.statements: list[str] = []

    async def execute(
        self, statement: str, parameters: tuple[object, ...] = ()
    ) -> _Cursor:
        del parameters
        self.statements.append(statement)
        return _Cursor((self.blocked,))


class _UnitOfWork:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection

    def _connection_for_repository(self) -> _Connection:
        return self.connection

    @property
    def transaction(self) -> _Connection:
        return self.connection


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "code", ["DB-TX-SERIALIZATION", "DB-TX-DEADLOCK", "DB-TX-COMMIT-UNKNOWN"]
)
async def test_deletion_retries_only_rolled_back_settlement_without_repeating_physical_effect(
    code: str,
):
    @asynccontextmanager
    async def unit_of_work(**kwargs):
        yield SimpleNamespace()

    error = RuntimeTransactionFailure()
    error.code = code
    repository = SimpleNamespace(
        prepare=AsyncMock(return_value=(uuid7(),)),
        reconcile_artifacts=AsyncMock(),
        finalize=AsyncMock(side_effect=[error, None]),
    )
    lifecycle = SimpleNamespace(run_once=AsyncMock())
    executor = LocalDataDeletionExecutor(
        repository=cast(Any, repository),
        lifecycle=cast(Any, lifecycle),
        unit_of_work_factory=cast(Any, SimpleNamespace(unit_of_work=unit_of_work)),
    )
    if code == "DB-TX-COMMIT-UNKNOWN":
        with pytest.raises(DataRightsViolation) as failure:
            await executor.execute(uuid7())
        assert failure.value.code == "DATA-RIGHTS-UNAVAILABLE"
        assert repository.finalize.await_count == 1
    else:
        await executor.execute(uuid7())
        assert repository.finalize.await_count == 2
    assert repository.prepare.await_count == 1
    assert lifecycle.run_once.await_count == 1


def test_data_rights_core_seals_exactly_once() -> None:
    core = bootstrap_data_rights_core()
    gate = core.gate

    assert core.seal() is gate
    with pytest.raises(RuntimeError):
        core.seal()


def test_three_order_kinds_are_explicit_and_bounded() -> None:
    for kind in DataRightsOrderKind:
        command = DataRightsOrderCommand(
            kind,
            IdempotencyKey(f"data-right-{kind.value}"),
            TraceId("1" * 32),
        )
        assert command.order_kind is kind
    with pytest.raises(ValueError):
        DataRightsOrderKind("delete_all_life")


@pytest.mark.asyncio
async def test_stale_deletion_preview_is_rejected_before_owner_writes():
    party = uuid7()
    unit = SimpleNamespace(transaction=AsyncMock())
    context = AsyncMock()
    context.__aenter__.return_value = unit
    context.__aexit__.return_value = False
    factory = SimpleNamespace(
        environment_id=uuid7(), unit_of_work=Mock(return_value=context)
    )
    repository = Mock(spec=DataRightsOrderRepository)
    repository.find_existing.return_value = None
    deletion = Mock(spec=LocalDataDeletionExecutor)
    deletion.preview_in.return_value = DataRightsDeletionPreview(
        party, Digest.from_bytes(b"changed"), ()
    )
    service = object.__new__(DataRightsOrderService)
    service._uow_factory = cast(Any, factory)
    service._repository = repository
    service._deletion = deletion
    service._creator_party_id = party
    service._parties = cast(
        Any, SimpleNamespace(creator_party=AsyncMock(return_value=party))
    )
    with pytest.raises(DataRightsViolation) as error:
        await service._record_request(
            requester_kind=DataRightsRequesterKind.CREATOR,
            party_key=None,
            command=DataRightsOrderCommand(
                DataRightsOrderKind.DELETE_RELATED,
                IdempotencyKey("stale-delete"),
                TraceId(uuid7().hex),
                Digest.from_bytes(b"approved"),
            ),
            requester_party_id=party,
        )
    assert error.value.code == "DATA-RIGHTS-PREVIEW-STALE"
    repository.advance_fence.assert_not_called()
    repository.insert.assert_not_called()
    deletion.prepare_in.assert_not_called()
    preview = await service.preview_deletion(None)
    assert preview.party_id == party
    assert factory.unit_of_work.call_args.kwargs["read_only"] is True


@pytest.mark.asyncio
async def test_find_deletion_request_checks_exact_owner_key_without_writing():
    party = uuid7()
    context = AsyncMock()
    factory = SimpleNamespace(unit_of_work=Mock(return_value=context))
    repository = Mock(spec=DataRightsOrderRepository)
    snapshot = DataRightsOrderSnapshot(
        uuid7(),
        party,
        DataRightsRequesterKind.CREATOR,
        DataRightsOrderKind.DELETE_RELATED,
        DataRightsScopeKind.PARTY_LOCAL_DATA,
        party,
        DataRightsExecutionStatus.PENDING,
        "original-key",
        Digest.from_bytes(b"request"),
        Instant(datetime.now(UTC)),
        None,
    )
    repository.find_existing.return_value = snapshot
    service = object.__new__(DataRightsOrderService)
    service._uow_factory = cast(Any, factory)
    service._repository = repository
    service._creator_party_id = party
    service._parties = cast(
        Any, SimpleNamespace(creator_party=AsyncMock(return_value=party))
    )
    found = await service.find_deletion_request(None, IdempotencyKey("original-key"))
    assert found is not None and found.order_id == snapshot.order_id
    assert found.newly_created is False
    assert (
        await service.find_deletion_request(None, IdempotencyKey("other-key")) is None
    )
    assert factory.unit_of_work.call_args.kwargs["read_only"] is True
    repository.insert.assert_not_called()
    repository.advance_fence.assert_not_called()


def test_delete_related_tracks_pending_and_terminal_s015_execution() -> None:
    party_id = uuid7()
    now = Instant(datetime.now(UTC))
    result = DataRightsOrderResult(
        uuid7(),
        party_id,
        DataRightsRequesterKind.OTHER_HUMAN,
        DataRightsOrderKind.DELETE_RELATED,
        DataRightsScopeKind.PARTY_LOCAL_DATA,
        party_id,
        "effective",
        DataRightsExecutionStatus.PENDING,
        Digest.from_bytes(b"request"),
        now,
        None,
        True,
    )
    assert result.execution_status is DataRightsExecutionStatus.PENDING
    for status in (
        DataRightsExecutionStatus.COMPLETED,
        DataRightsExecutionStatus.PARTIAL,
    ):
        settled = DataRightsOrderResult(
            uuid7(),
            party_id,
            DataRightsRequesterKind.OTHER_HUMAN,
            DataRightsOrderKind.DELETE_RELATED,
            DataRightsScopeKind.PARTY_LOCAL_DATA,
            party_id,
            "effective",
            status,
            Digest.from_bytes(b"request"),
            now,
            now,
            False,
        )
        assert settled.completed_at == now
    with pytest.raises(DataRightsViolation):
        DataRightsOrderResult(
            uuid7(),
            party_id,
            DataRightsRequesterKind.OTHER_HUMAN,
            DataRightsOrderKind.DELETE_RELATED,
            DataRightsScopeKind.PARTY_LOCAL_DATA,
            party_id,
            "effective",
            DataRightsExecutionStatus.PENDING,
            Digest.from_bytes(b"request"),
            now,
            now,
            True,
        )


def test_deletion_item_retry_only_updates_a_granted_settlement_column() -> None:
    statement = inspect.getsource(LocalDataDeletionRepository._insert_target)
    assert "SET result_status = armi.data_rights_order_items.result_status" in statement
    assert "SET target_ref = EXCLUDED.target_ref" not in statement


@pytest.mark.parametrize("blocked", [False, True])
def test_effective_order_guard_controls_new_interactions(blocked: bool) -> None:
    connection = _Connection(blocked)
    repository = DataRightsOrderRepository()
    observed = asyncio.run(
        repository.blocks_new_interaction(
            cast(PostgreSQLRuntimeUnitOfWork, _UnitOfWork(connection)),
            uuid7(),
        )
    )
    assert observed is blocked
    assert "pg_advisory_xact_lock" in connection.statements[0]
    statement = connection.statements[1]
    assert "status = 'effective'" in statement
    assert "'stop_contact', 'stop_use', 'delete_related'" in statement
