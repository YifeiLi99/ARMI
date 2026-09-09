"""Bind local upload completion to governed artifact publication."""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import UUID

from armi_artifact_store.api import ArtifactCatalogPort
from armi_artifact_store.content_store import ContentAddressedArtifactStore
from armi_kernel.application import ArtifactId, ArtifactPolicy, ArtifactPrivacyScope
from armi_kernel.contracts import TraceId
from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWorkFactory

from armi_runtime.application.media_uploads import (
    MediaUploads,
    UploadRecord,
    UploadViolation,
)


def compose_media_uploads(
    root: Path,
    environment_id: UUID,
    generation_id: UUID,
    factory: PostgreSQLRuntimeUnitOfWorkFactory,
    catalog: ArtifactCatalogPort,
) -> MediaUploads:
    storage = ContentAddressedArtifactStore(
        root / "artifacts",
        max_object_bytes=45 * 1024 * 1024,
        publication_catalog=catalog,
        publication_uow_factory=factory,
    )

    async def publish(record: UploadRecord, path: Path) -> UUID:
        await storage.prepare()

        async def chunks():
            with path.open("rb") as stream:
                while content := await asyncio.to_thread(stream.read, 128 * 1024):
                    yield content

        staged = await storage.stage(
            chunks(),
            ArtifactPolicy(
                media_type=record.declaration.media_type,
                logical_kind="creator.input.media",
                producer_kind="creator.delegate",
                producer_trace_id=TraceId(record.upload_id.hex),
                privacy_scope=ArtifactPrivacyScope.CREATOR_VISIBLE,
            ),
        )
        if (
            staged.content_digest.value != record.declaration.content_digest
            or staged.byte_size != record.declaration.byte_size
        ):
            await storage.discard(staged)
            raise UploadViolation("UPLOAD-DIGEST")
        published = await storage.publish(staged)
        async with factory.unit_of_work() as unit:
            if (
                unit.runtime_fence is None
                or unit.runtime_fence.life_generation_id != generation_id
            ):
                raise UploadViolation("UPLOAD-GENERATION")
            registered = await catalog.register(
                unit, ArtifactId(record.upload_id), published
            )
        return registered.ref.artifact_id.value

    return MediaUploads(root / "uploads", environment_id, generation_id, publish)


__all__ = ("compose_media_uploads",)
