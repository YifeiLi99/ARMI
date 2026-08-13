"""Durable execution of ARMI-selected exact life-record queries."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any, cast
from uuid import uuid7

import rfc8785
from armi_artifact_store.bootstrap import bootstrap_artifact_catalog
from armi_artifact_store.content_store import (
    ContentAddressedArtifactStore,
)
from armi_kernel.application import (
    ArtifactId,
    ArtifactPolicy,
    ArtifactPrivacyScope,
    ArtifactViolation,
    LifeRecordActor,
    LifeRecordPage,
    LifeRecordQuery,
    LifeRecordQueryPort,
    LifeRecordQueryViolation,
    LifeRecordRetrievalKind,
    WorkLease,
    WorkViolation,
)

from armi_runtime.adapters.persistence.durable_work import (
    PostgreSQLDurableWorkGateway,
)
from armi_runtime.adapters.persistence.exact_life_query import (
    ExactLifeQuerySnapshot,
    PostgreSQLExactLifeQueryRepository,
)
from armi_runtime.adapters.persistence.unit_of_work import (
    PostgreSQLUnitOfWorkFactory,
)
from armi_runtime.adapters.transaction_errors import DatabaseTransactionError

from .work_wakeup import (
    EXACT_LIFE_QUERY,
    OPPORTUNITY_AVAILABLE,
    WorkWakeupBus,
)

_WORK_KIND = "life.query.execute"
Diagnostic = Callable[[str], None]


def _ignore_diagnostic(_event: str) -> None:
    return None


class ExactLifeQueryPipeline:
    """Execute only the typed subject query port and admit its result evidence."""

    __slots__ = (
        "_catalog",
        "_diagnostic",
        "_factory",
        "_lease_owner",
        "_query",
        "_repository",
        "_stop",
        "_storage",
        "_wakeups",
        "_work",
    )

    def __init__(
        self,
        *,
        factory: PostgreSQLUnitOfWorkFactory,
        storage: ContentAddressedArtifactStore,
        query: LifeRecordQueryPort,
        wakeups: WorkWakeupBus | None = None,
        diagnostic: Diagnostic | None = None,
    ) -> None:
        self._factory = factory
        self._storage = storage
        self._query = query
        self._catalog = bootstrap_artifact_catalog()
        self._repository = PostgreSQLExactLifeQueryRepository()
        self._work = PostgreSQLDurableWorkGateway(factory)
        self._wakeups = wakeups or WorkWakeupBus()
        self._lease_owner = uuid7()
        self._stop = asyncio.Event()
        self._diagnostic = diagnostic or _ignore_diagnostic

    async def open(self) -> None:
        try:
            await self._storage.prepare()
        except ArtifactViolation:
            raise LifeRecordQueryViolation("LIFE-QUERY-ARTIFACT") from None

    async def close(self) -> None:
        self._stop.set()

    def stop(self) -> None:
        self._stop.set()

    async def execute_once(self) -> bool:
        try:
            records = await self._work.claim(
                work_kind=_WORK_KIND,
                lease_owner=self._lease_owner,
                lease_seconds=30,
                limit=1,
            )
        except WorkViolation:
            raise LifeRecordQueryViolation("LIFE-QUERY-DATABASE") from None
        if not records:
            return False
        lease = cast(WorkLease, records[0].lease)
        try:
            async with self._factory.unit_of_work() as unit:
                snapshot = await self._repository.snapshot(unit, lease)
            status, page, failure_code = await self._execute_query(snapshot)
            result_bytes = _result_bytes(
                snapshot,
                status=status,
                page=page,
                failure_code=failure_code,
            )
            published = await self._publish(result_bytes, snapshot)
            async with self._factory.unit_of_work() as unit:
                registration = await self._catalog.register(
                    unit,
                    ArtifactId(uuid7()),
                    published,
                )
                await self._repository.settle(
                    unit,
                    lease=lease,
                    snapshot=snapshot,
                    status=status,
                    result_artifact_id=registration.ref.artifact_id,
                    result_count=0 if page is None else len(page.items),
                    failure_code=failure_code,
                )
            self._wakeups.notify(OPPORTUNITY_AVAILABLE)
            return True
        except LifeRecordQueryViolation as error:
            if error.code == "LIFE-QUERY-WORK-STALE":
                self._diagnostic("life.query.work.stale")
                return True
            await self._fail(lease, error.code)
            return True
        except ArtifactViolation:
            await self._fail(lease, "LIFE-QUERY-ARTIFACT")
            return True
        except DatabaseTransactionError, WorkViolation:
            self._diagnostic("life.query.worker.transient_failure")
            return True

    async def _fail(self, lease: WorkLease, code: str) -> None:
        try:
            async with self._factory.unit_of_work() as unit:
                await self._repository.fail(unit, lease=lease, code=code)
        except DatabaseTransactionError, LifeRecordQueryViolation, WorkViolation:
            self._diagnostic("life.query.settlement.deferred")

    async def run_worker(self) -> None:
        observed = self._wakeups.version(EXACT_LIFE_QUERY)
        while not self._stop.is_set():
            try:
                worked = await self.execute_once()
            except LifeRecordQueryViolation:
                if not self._stop.is_set():
                    self._diagnostic("life.query.worker.failed")
                worked = False
            if worked:
                await asyncio.sleep(0)
                continue
            observed = await self._wakeups.wait(
                EXACT_LIFE_QUERY,
                observed,
                stop=self._stop,
                timeout_seconds=1,
            )

    async def _execute_query(
        self,
        snapshot: ExactLifeQuerySnapshot,
    ) -> tuple[str, LifeRecordPage | None, str | None]:
        try:
            page = await self._query.query(
                LifeRecordQuery(
                    actor=LifeRecordActor.SUBJECT,
                    retrieval_kind=LifeRecordRetrievalKind.EXACT_QUERY,
                    limit=snapshot.limit,
                    record_kind=snapshot.record_kind,
                    query_text=snapshot.query_text,
                )
            )
        except LifeRecordQueryViolation as error:
            failure_code = (
                error.code
                if error.code.startswith("LIFE-QUERY-")
                else "LIFE-QUERY-UNAVAILABLE"
            )
            return (
                "denied" if failure_code == "LIFE-QUERY-NOT-AUTHORIZED" else "failed",
                None,
                failure_code,
            )
        if any(
            item.retrieval_kind is not LifeRecordRetrievalKind.EXACT_QUERY
            or item.record_kind is not snapshot.record_kind
            for item in page.items
        ):
            return "failed", None, "LIFE-QUERY-SCOPE"
        return ("succeeded" if page.items else "empty"), page, None

    async def _publish(
        self,
        value: bytes,
        snapshot: ExactLifeQuerySnapshot,
    ):
        staged = await self._storage.stage(
            _one_chunk(value),
            ArtifactPolicy(
                "application/json",
                "life.query.result",
                "life.query",
                snapshot.trace_id,
                ArtifactPrivacyScope.PRIVATE,
            ),
        )
        return await self._storage.publish(staged)


def _result_bytes(
    snapshot: ExactLifeQuerySnapshot,
    *,
    status: str,
    page: LifeRecordPage | None,
    failure_code: str | None,
) -> bytes:
    items = () if page is None else page.items
    value = {
        "schema_version": "armi.exact-life-query-result.v1",
        "status": status,
        "retrieval_kind": "exact_query",
        "record_kind": snapshot.record_kind.value,
        "query_text": snapshot.query_text,
        "returned_count": len(items),
        "truncated": page is not None and page.next_cursor is not None,
        "failure_code": failure_code,
        "items": [
            {
                "record_ref": str(item.record_ref),
                "record_kind": item.record_kind.value,
                "summary": item.summary,
                "source_kind": item.source_kind,
                "occurred_at": item.occurred_at.to_wire(),
                "naturally_recallable": item.naturally_recallable,
                "retrieval_kind": item.retrieval_kind.value,
            }
            for item in items
        ],
    }
    return rfc8785.dumps(cast(Any, value))


async def _one_chunk(value: bytes) -> AsyncIterator[bytes]:
    yield value


def build_exact_life_query_pipeline(
    factory: PostgreSQLUnitOfWorkFactory,
    *,
    data_root: Path,
    max_object_bytes: int,
    query: LifeRecordQueryPort,
    wakeups: WorkWakeupBus | None = None,
    diagnostic: Diagnostic | None = None,
) -> ExactLifeQueryPipeline:
    return ExactLifeQueryPipeline(
        factory=factory,
        storage=ContentAddressedArtifactStore(
            data_root / "artifacts",
            max_object_bytes=max_object_bytes,
        ),
        query=query,
        wakeups=wakeups,
        diagnostic=diagnostic,
    )


__all__ = ("ExactLifeQueryPipeline", "build_exact_life_query_pipeline")
