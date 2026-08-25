"""PostgreSQL catalog owned by the artifact-store distribution."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, LiteralString
from uuid import uuid7

from armi_kernel.application import (
    ArtifactId,
    ArtifactIntegrityStatus,
    ArtifactPrivacyScope,
    ArtifactPublication,
    ArtifactRef,
    ArtifactRegistration,
    ArtifactViolation,
    StagedArtifact,
    WorkDraft,
    WorkId,
    WorkOwner,
    WorkPayloadRef,
    WorkType,
)
from armi_kernel.contracts import Digest, IdempotencyKey, Instant, TraceId
from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWork, PostgreSQLTransaction

from .api import ArtifactRetirement

_REF_SELECT = """a.artifact_id,o.content_digest,o.byte_size,a.media_type,
                         a.logical_kind,a.privacy_scope,o.integrity_status"""


class PostgreSQLArtifactCatalog:
    async def export_records(
        self, transaction: PostgreSQLTransaction
    ) -> tuple[tuple[str, tuple[bytes, ...]], ...]:
        statements: tuple[tuple[str, LiteralString], ...] = (
            (
                "artifacts",
                "SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8') FROM armi.artifacts AS source ORDER BY to_jsonb(source)::text",
            ),
            (
                "artifact_objects",
                "SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8') FROM armi.artifact_objects AS source ORDER BY to_jsonb(source)::text",
            ),
            (
                "artifact_publications",
                "SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8') FROM armi.artifact_publications AS source ORDER BY to_jsonb(source)::text",
            ),
            (
                "artifact_object_deletions",
                "SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8') FROM armi.artifact_object_deletions AS source ORDER BY to_jsonb(source)::text",
            ),
            (
                "artifact_object_deletion_attempts",
                "SELECT convert_to(to_jsonb(source)::text || chr(10), 'UTF8') FROM armi.artifact_object_deletion_attempts AS source ORDER BY to_jsonb(source)::text",
            ),
        )
        result: list[tuple[str, tuple[bytes, ...]]] = []
        for name, statement in statements:
            rows = await (await transaction.execute(statement)).fetchall()
            result.append((name, tuple(bytes(row[0]) for row in rows)))
        return tuple(result)

    async def observation(
        self, transaction: PostgreSQLTransaction
    ) -> tuple[tuple[tuple[str, int], ...], int]:
        rows = await (
            await transaction.execute(
                """SELECT integrity_status,count(*),COALESCE(sum(byte_size),0)
                   FROM armi.artifact_objects GROUP BY integrity_status
                   ORDER BY integrity_status"""
            )
        ).fetchall()
        return (
            tuple((str(row[0]), int(row[1])) for row in rows),
            sum(int(row[2]) for row in rows),
        )

    async def reserve_publication(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        staged: StagedArtifact,
        *,
        orphan_grace_seconds: int,
    ) -> ArtifactPublication:
        transaction = unit_of_work.transaction
        digest = staged.content_digest.value
        digest_hex = digest.removeprefix("sha256:")
        locator = f"objects/sha256/{digest_hex[:2]}/{digest_hex[2:4]}/{digest_hex}"
        await transaction.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            (f"artifact-object:{digest}",),
        )
        row = await (
            await transaction.execute(
                """SELECT artifact_object_id,byte_size,generation,object_status
                   FROM armi.artifact_objects WHERE content_digest=%s FOR UPDATE""",
                (digest,),
            )
        ).fetchone()
        if row is None:
            object_id, generation = uuid7(), 1
            await transaction.execute(
                """INSERT INTO armi.artifact_objects
                   (artifact_object_id,content_digest,byte_size,storage_locator,
                    generation,object_status,integrity_status)
                   VALUES (%s,%s,%s,%s,%s,'publishing','verified')""",
                (object_id, digest, staged.byte_size, locator, generation),
            )
        else:
            object_id, generation = row[0], int(row[2])
            if int(row[1]) != staged.byte_size:
                raise ArtifactViolation("ART-METADATA-CONFLICT")
            status = str(row[3])
            if status in {"absent", "corrupt"}:
                generation += 1
                await transaction.execute(
                    """UPDATE armi.artifact_objects
                       SET generation=%s,object_status='publishing',
                           integrity_status='verified',updated_at=clock_timestamp()
                       WHERE artifact_object_id=%s""",
                    (generation, object_id),
                )
                await transaction.execute(
                    """UPDATE armi.artifact_object_deletions
                       SET status='cancelled',completed_at=clock_timestamp(),
                           updated_at=clock_timestamp(),
                           last_error_code='ART-GENERATION-ADVANCED'
                       WHERE artifact_object_id=%s
                         AND status IN ('ready','retry_wait','retiring')""",
                    (object_id,),
                )
            elif status not in {"available", "publishing"}:
                raise ArtifactViolation("ART-OBJECT-BUSY")
        publication_id = staged.stage_id
        await transaction.execute(
            """INSERT INTO armi.artifact_publications
               (publication_id,artifact_object_id,object_generation,
                declaration_digest,status,expires_at)
               VALUES (%s,%s,%s,%s,'reserved',
                       clock_timestamp()+(%s * interval '1 second'))
               ON CONFLICT (publication_id) DO NOTHING""",
            (
                publication_id.value,
                object_id,
                generation,
                digest,
                orphan_grace_seconds,
            ),
        )
        publication = await (
            await transaction.execute(
                """SELECT artifact_object_id,object_generation,declaration_digest,status
                   FROM armi.artifact_publications WHERE publication_id=%s""",
                (publication_id.value,),
            )
        ).fetchone()
        if publication is None or (
            publication[0] != object_id
            or int(publication[1]) != generation
            or str(publication[2]) != digest
            or str(publication[3]) not in {"reserved", "published"}
        ):
            raise ArtifactViolation("ART-PUBLICATION-CONFLICT")
        return ArtifactPublication(
            publication_id,
            object_id,
            generation,
            staged.content_digest,
            staged.byte_size,
            staged.policy,
        )

    async def mark_publication_published(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        publication: ArtifactPublication,
    ) -> None:
        result = await unit_of_work.transaction.execute(
            """UPDATE armi.artifact_publications p
               SET status='published',published_at=COALESCE(published_at,clock_timestamp())
               FROM armi.artifact_objects o
               WHERE p.publication_id=%s AND p.artifact_object_id=%s
                 AND p.object_generation=%s AND p.declaration_digest=%s
                 AND p.status IN ('reserved','published')
                 AND o.artifact_object_id=p.artifact_object_id
                 AND o.generation=p.object_generation""",
            (
                publication.publication_id.value,
                publication.artifact_object_id,
                publication.object_generation,
                publication.content_digest.value,
            ),
        )
        if result.rowcount != 1:
            raise ArtifactViolation("ART-PUBLICATION-CONFLICT")
        await unit_of_work.transaction.execute(
            """UPDATE armi.artifact_objects SET object_status='available',
                      integrity_status='verified',updated_at=clock_timestamp()
               WHERE artifact_object_id=%s AND generation=%s""",
            (publication.artifact_object_id, publication.object_generation),
        )

    async def abandon_publication(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        publication: ArtifactPublication,
    ) -> None:
        await unit_of_work.transaction.execute(
            """UPDATE armi.artifact_publications SET status='abandoned'
               WHERE publication_id=%s AND status='reserved'""",
            (publication.publication_id.value,),
        )
        await unit_of_work.transaction.execute(
            """UPDATE armi.artifact_objects o SET object_status='absent',
                      integrity_status='missing',updated_at=clock_timestamp()
               WHERE o.artifact_object_id=%s AND o.generation=%s
                 AND o.object_status='publishing'
                 AND NOT EXISTS (
                     SELECT 1 FROM armi.artifact_publications p
                     WHERE p.artifact_object_id=o.artifact_object_id
                       AND p.object_generation=o.generation
                       AND p.status IN ('reserved','published','consumed'))""",
            (publication.artifact_object_id, publication.object_generation),
        )

    async def register(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        artifact_id: ArtifactId,
        published: ArtifactPublication,
    ) -> ArtifactRegistration:
        transaction = unit_of_work.transaction
        publication = await (
            await transaction.execute(
                """SELECT p.status,o.object_status,o.byte_size
                   FROM armi.artifact_publications p
                   JOIN armi.artifact_objects o USING (artifact_object_id)
                   WHERE p.publication_id=%s AND p.artifact_object_id=%s
                     AND p.object_generation=%s AND p.declaration_digest=%s
                   FOR UPDATE OF p,o""",
                (
                    published.publication_id.value,
                    published.artifact_object_id,
                    published.object_generation,
                    published.content_digest.value,
                ),
            )
        ).fetchone()
        if publication is None or (
            str(publication[0]) not in {"published", "consumed"}
            or str(publication[1]) != "available"
            or int(publication[2]) != published.byte_size
        ):
            raise ArtifactViolation("ART-PUBLICATION-NOT-PUBLISHED")
        object_id = published.artifact_object_id
        generation = published.object_generation
        inserted_row = await (
            await transaction.execute(
                """INSERT INTO armi.artifacts
                   (artifact_id,artifact_object_id,object_generation,media_type,
                    logical_kind,producer_kind,producer_trace_id,privacy_scope)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (artifact_id) DO NOTHING RETURNING artifact_id""",
                (
                    artifact_id.value,
                    object_id,
                    generation,
                    published.policy.media_type,
                    published.policy.logical_kind,
                    published.policy.producer_kind,
                    published.policy.producer_trace_id.value,
                    published.policy.privacy_scope.value,
                ),
            )
        ).fetchone()
        row = await (
            await transaction.execute(
                f"""SELECT {_REF_SELECT},a.artifact_object_id,a.object_generation,
                            a.producer_kind,a.producer_trace_id
                     FROM armi.artifacts a JOIN armi.artifact_objects o
                       USING (artifact_object_id) WHERE a.artifact_id=%s""",
                (artifact_id.value,),
            )
        ).fetchone()
        if row is None:
            raise ArtifactViolation("ART-DATABASE")
        ref = _row_to_ref(row)
        if (
            ref.content_digest != published.content_digest
            or ref.byte_size != published.byte_size
            or ref.media_type != published.policy.media_type
            or ref.logical_kind != published.policy.logical_kind
            or ref.privacy_scope is not published.policy.privacy_scope
            or row[7] != object_id
            or int(row[8]) != generation
            or str(row[9]) != published.policy.producer_kind
            or str(row[10]) != published.policy.producer_trace_id.value
        ):
            raise ArtifactViolation("ART-IDEMPOTENCY-CONFLICT")
        await transaction.execute(
            """UPDATE armi.artifact_publications
               SET status='consumed',consumed_at=COALESCE(consumed_at,clock_timestamp())
               WHERE publication_id=%s AND status IN ('published','consumed')""",
            (published.publication_id.value,),
        )
        return ArtifactRegistration(ref, inserted_row is not None)

    async def get(
        self, unit_of_work: PostgreSQLRuntimeUnitOfWork, artifact_id: ArtifactId
    ) -> ArtifactRef:
        row = await self._ref_row(unit_of_work.transaction, artifact_id, retained=False)
        if row is None:
            raise ArtifactViolation("ART-NOT-FOUND")
        return _row_to_ref(row)

    async def all_refs(
        self, unit_of_work: PostgreSQLRuntimeUnitOfWork
    ) -> tuple[ArtifactRef, ...]:
        return await self.all_refs_in(unit_of_work.transaction)

    async def all_refs_in(
        self, transaction: PostgreSQLTransaction
    ) -> tuple[ArtifactRef, ...]:
        rows = await (
            await transaction.execute(
                f"""SELECT {_REF_SELECT} FROM armi.artifacts a
                     JOIN armi.artifact_objects o USING (artifact_object_id)
                     WHERE a.retention_status='retained'
                     ORDER BY o.content_digest,a.artifact_id"""
            )
        ).fetchall()
        return tuple(_row_to_ref(row) for row in rows)

    async def retained_ref(
        self, unit_of_work: PostgreSQLRuntimeUnitOfWork, artifact_id: ArtifactId
    ) -> ArtifactRef | None:
        return await self.retained_ref_in(unit_of_work.transaction, artifact_id)

    async def retained_ref_in(
        self, transaction: PostgreSQLTransaction, artifact_id: ArtifactId
    ) -> ArtifactRef | None:
        row = await self._ref_row(transaction, artifact_id, retained=True)
        return None if row is None else _row_to_ref(row)

    async def retire_artifact(
        self, unit_of_work: PostgreSQLRuntimeUnitOfWork, artifact_id: ArtifactId
    ) -> ArtifactRetirement:
        transaction = unit_of_work.transaction
        row = await (
            await transaction.execute(
                """SELECT artifact_object_id,object_generation,retention_status,
                          producer_trace_id
                   FROM armi.artifacts WHERE artifact_id=%s FOR UPDATE""",
                (artifact_id.value,),
            )
        ).fetchone()
        if row is None:
            raise ArtifactViolation("ART-NOT-FOUND")
        object_id, generation = row[0], int(row[1])
        changed = str(row[2]) == "retained"
        if changed:
            await transaction.execute(
                """UPDATE armi.artifacts SET retention_status='deleted',
                          deleted_at=clock_timestamp() WHERE artifact_id=%s""",
                (artifact_id.value,),
            )
        count_row = await (
            await transaction.execute(
                """SELECT count(*) FROM armi.artifacts
                   WHERE artifact_object_id=%s AND object_generation=%s
                     AND retention_status='retained'""",
                (object_id, generation),
            )
        ).fetchone()
        if count_row is None:
            raise ArtifactViolation("ART-DATABASE")
        if int(count_row[0]):
            return ArtifactRetirement(
                artifact_id.value, object_id, generation, None, True, changed
            )
        proposed_deletion_id = uuid7()
        deletion_row = await (
            await transaction.execute(
                """INSERT INTO armi.artifact_object_deletions
                   (artifact_object_deletion_id,artifact_object_id,
                    object_generation,status)
                   VALUES (%s,%s,%s,'ready')
                   ON CONFLICT (artifact_object_id,object_generation) DO UPDATE
                   SET updated_at=armi.artifact_object_deletions.updated_at
                   RETURNING artifact_object_deletion_id""",
                (proposed_deletion_id, object_id, generation),
            )
        ).fetchone()
        if deletion_row is None:
            raise ArtifactViolation("ART-DATABASE")
        deletion_id = deletion_row[0]
        now = datetime.now(UTC)
        payload_digest = Digest(
            "sha256:" + hashlib.sha256(f"{object_id}:{generation}".encode()).hexdigest()
        )
        await unit_of_work.work.enqueue(
            WorkDraft(
                work_id=WorkId(deletion_id),
                work_kind=WorkType.ARTIFACT_OBJECT_DELETE,
                owner=WorkOwner("artifact_object_deletion", deletion_id),
                idempotency_key=IdempotencyKey(f"artifact-delete:{deletion_id.hex}"),
                payload_digest=payload_digest,
                priority=50,
                not_before=Instant(now),
                deadline_at=Instant(now + timedelta(minutes=59)),
                max_attempts=8,
                trace_id=TraceId(str(row[3])),
                payload=WorkPayloadRef("artifact_object", object_id),
            )
        )
        return ArtifactRetirement(
            artifact_id.value, object_id, generation, deletion_id, False, changed
        )

    async def mark_integrity(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        artifact_id: ArtifactId,
        status: ArtifactIntegrityStatus,
    ) -> bool:
        if status not in {
            ArtifactIntegrityStatus.MISSING,
            ArtifactIntegrityStatus.CORRUPT,
        }:
            raise ArtifactViolation("ART-STATE")
        object_status = (
            "absent" if status is ArtifactIntegrityStatus.MISSING else "corrupt"
        )
        result = await unit_of_work.transaction.execute(
            """UPDATE armi.artifact_objects o
               SET integrity_status=%s,object_status=%s,updated_at=clock_timestamp()
               FROM armi.artifacts a WHERE a.artifact_id=%s
                 AND a.artifact_object_id=o.artifact_object_id
                 AND o.integrity_status='verified'""",
            (status.value, object_status, artifact_id.value),
        )
        if result.rowcount not in (0, 1):
            raise ArtifactViolation("ART-DATABASE")
        return result.rowcount == 1

    async def _ref_row(
        self,
        transaction: PostgreSQLTransaction,
        artifact_id: ArtifactId,
        *,
        retained: bool,
    ) -> Sequence[Any] | None:
        retention = " AND a.retention_status='retained'" if retained else ""
        return await (
            await transaction.execute(
                f"""SELECT {_REF_SELECT} FROM armi.artifacts a
                     JOIN armi.artifact_objects o USING (artifact_object_id)
                     WHERE a.artifact_id=%s{retention}""",
                (artifact_id.value,),
            )
        ).fetchone()


def _row_to_ref(row: Sequence[Any]) -> ArtifactRef:
    try:
        return ArtifactRef(
            ArtifactId(row[0]),
            Digest(str(row[1])),
            int(row[2]),
            str(row[3]),
            str(row[4]),
            ArtifactPrivacyScope(str(row[5])),
            ArtifactIntegrityStatus(str(row[6])),
        )
    except ArtifactViolation, TypeError, ValueError:
        raise ArtifactViolation("ART-DATABASE") from None


__all__ = ("PostgreSQLArtifactCatalog",)
