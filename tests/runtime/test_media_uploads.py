"""Durable upload transport behavior, independent from provider effects."""

import hashlib
from pathlib import Path
from uuid import uuid7

import pytest
from armi_runtime.application.media_uploads import (
    MediaUploads,
    UploadDeclaration,
    UploadViolation,
)

pytestmark = pytest.mark.asyncio


def declaration(content: bytes) -> UploadDeclaration:
    return UploadDeclaration(
        file_name="notes.txt",
        media_type="text/plain",
        byte_size=len(content),
        content_digest="sha256:" + hashlib.sha256(content).hexdigest(),
    )


async def test_resume_repeated_chunks_and_complete(tmp_path: Path):
    environment, generation, creator, delegate = (uuid7() for _ in range(4))
    content = "真实附件内容".encode() * 30000
    publications = []

    async def publish(record, path):
        publications.append(path.read_bytes())
        return record.upload_id

    uploads = MediaUploads(tmp_path / "uploads", environment, generation, publish)
    record = await uploads.begin(creator, delegate, "file-1", declaration(content))
    assert not publications
    chunk = content[: uploads.chunk_bytes]
    first = await uploads.append(record.upload_id, creator, delegate, 0, chunk)
    repeated = await uploads.append(record.upload_id, creator, delegate, 0, chunk)
    assert repeated == first
    uploads = MediaUploads(tmp_path / "uploads", environment, generation, publish)
    resumed = await uploads.begin(creator, delegate, "file-1", declaration(content))
    assert resumed.received_bytes == len(chunk)
    while resumed.received_bytes < len(content):
        offset = resumed.received_bytes
        resumed = await uploads.append(
            record.upload_id,
            creator,
            delegate,
            offset,
            content[offset : offset + uploads.chunk_bytes],
        )
    completed = await uploads.complete(record.upload_id, creator, delegate)
    assert completed.state == "completed"
    assert publications == [content]
    assert await uploads.complete(record.upload_id, creator, delegate) == completed
    assert len(publications) == 1
    assert not list((tmp_path / "uploads").glob("*.part"))


async def test_scope_conflict_cancel_and_digest(tmp_path: Path):
    async def publish(record, path):
        pytest.fail("invalid or cancelled uploads must not publish")

    environment, generation, creator, delegate = (uuid7() for _ in range(4))
    uploads = MediaUploads(tmp_path / "uploads", environment, generation, publish)
    record = await uploads.begin(creator, delegate, "key", declaration(b"abc"))
    with pytest.raises(UploadViolation, match="UPLOAD-SCOPE"):
        await uploads.get(record.upload_id, creator, uuid7())
    with pytest.raises(UploadViolation, match="UPLOAD-IDEMPOTENCY-MISMATCH"):
        await uploads.begin(creator, delegate, "key", declaration(b"def"))
    await uploads.append(record.upload_id, creator, delegate, 0, b"ab")
    with pytest.raises(UploadViolation, match="UPLOAD-CHUNK-MISMATCH"):
        await uploads.append(record.upload_id, creator, delegate, 0, b"cd")
    await uploads.append(record.upload_id, creator, delegate, 2, b"d")
    with pytest.raises(UploadViolation, match="UPLOAD-DIGEST"):
        await uploads.complete(record.upload_id, creator, delegate)
    assert (
        await uploads.cancel(record.upload_id, creator, delegate)
    ).state == "cancelled"
    assert (
        await uploads.begin(creator, delegate, "key", declaration(b"abc"))
    ).state == "cancelled"
    with pytest.raises(UploadViolation, match="UPLOAD-STATE"):
        await uploads.append(record.upload_id, creator, delegate, 0, b"abc")


async def test_begin_recovers_record_after_lost_index_write(
    tmp_path: Path, monkeypatch
):
    async def publish(record, path):
        return record.upload_id

    uploads = MediaUploads(tmp_path / "uploads", uuid7(), uuid7(), publish)
    creator, delegate = uuid7(), uuid7()
    original = uploads._index

    def interrupted(*args):
        raise OSError("interrupted")

    monkeypatch.setattr(uploads, "_index", interrupted)
    with pytest.raises(OSError):
        await uploads.begin(creator, delegate, "key", declaration(b"abc"))
    monkeypatch.setattr(uploads, "_index", original)
    recovered = await uploads.begin(creator, delegate, "key", declaration(b"abc"))
    assert len(list((tmp_path / "uploads").glob("*.json"))) == 1
    assert (
        await uploads.begin(creator, delegate, "key", declaration(b"abc")) == recovered
    )


async def test_publication_reply_loss_resumes_with_same_owner_identity(tmp_path):
    published = set()
    fail_reply = True

    async def publish(record, path):
        nonlocal fail_reply
        published.add(record.upload_id)
        if fail_reply:
            fail_reply = False
            raise OSError("reply lost after publication")
        return record.upload_id

    environment, generation, creator, delegate = (uuid7() for _ in range(4))
    uploads = MediaUploads(tmp_path, environment, generation, publish)
    record = await uploads.begin(creator, delegate, "retry", declaration(b"abc"))
    await uploads.append(record.upload_id, creator, delegate, 0, b"abc")
    with pytest.raises(OSError):
        await uploads.complete(record.upload_id, creator, delegate)
    uploads = MediaUploads(tmp_path, environment, generation, publish)
    assert (
        await uploads.get(record.upload_id, creator, delegate)
    ).state == "publishing"
    with pytest.raises(UploadViolation):
        await uploads.cancel(record.upload_id, creator, delegate)
    assert (
        await uploads.complete(record.upload_id, creator, delegate)
    ).state == "completed"
    assert published == {record.upload_id}


@pytest.mark.parametrize("failure", ["failed", "unknown"])
async def test_media_operation_exposes_work_failure_without_waiting_forever(failure):
    from unittest.mock import AsyncMock

    from armi_interaction.api import CreatorMediaStatus
    from armi_runtime.application.creator_media import CreatorMedia

    reference = uuid7()
    inputs = AsyncMock()
    inputs.media_status.return_value = CreatorMediaStatus(
        reference, "pending", None, (), failure
    )
    media = CreatorMedia(AsyncMock(), inputs)
    cognition = AsyncMock()
    result = await media.operation(str(reference), cognition)
    assert result is not None and result["status"] == failure
    assert result["result_ref"] == str(reference)
    cognition.assert_not_called()


@pytest.mark.parametrize("attachment_status", ["failed", "unknown", "skipped"])
async def test_completed_cognition_keeps_partial_attachment_result(
    attachment_status, monkeypatch
):
    from unittest.mock import AsyncMock

    from armi_interaction.api import CreatorAttachmentStatus, CreatorMediaStatus
    from armi_runtime.application.creator_media import CreatorMedia

    reference, opportunity = uuid7(), uuid7()
    inputs = AsyncMock()
    inputs.media_status.return_value = CreatorMediaStatus(
        reference,
        "failed",
        opportunity,
        (
            CreatorAttachmentStatus(
                1, "unsupported.bin", attachment_status, "PERCEPTION-UNSUPPORTED"
            ),
        ),
    )
    cognition = {
        "status": "completed",
        "result_ref": str(opportunity),
        "contract_version": "1.0",
        "trace_id": uuid7().hex,
        "occurred_at": "2026-09-09T00:00:00.000000Z",
        "message": "Completed",
        "details": {
            "projection_version": "creator-operation.v7",
            "operation_ref": str(opportunity),
            "operation_kind": "cognition",
            "stage": "no_action",
            "outcome": "no_action",
        },
    }
    monkeypatch.setattr(
        "armi_runtime.application.creator_projection.operation_wire",
        lambda _: cognition,
    )
    result = await CreatorMedia(AsyncMock(), inputs).operation(
        str(reference), AsyncMock()
    )
    assert result is not None and result["status"] == "partial"
    assert result["attachments"][0]["status"] == attachment_status
    assert result["cognition"]["details"]["stage"] == "no_action"
