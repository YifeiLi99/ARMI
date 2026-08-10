from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import uuid7

import pytest
from armi_kernel.application import (
    MAX_CREATOR_PROMPT_BYTES,
    CreatorPromptRevisionCommand,
    CreatorPromptView,
    CreatorPromptViolation,
    PromptDocumentStatus,
    PromptKind,
    PromptRevisionKind,
)
from armi_kernel.contracts import Instant, TraceId


def test_creator_prompt_command_preserves_exact_utf8_content() -> None:
    command = CreatorPromptRevisionCommand(
        PromptKind.CREATOR_GUIDANCE,
        None,
        "  保留开头与结尾\n",
        TraceId("1" * 32),
    )

    assert command.content_bytes == "  保留开头与结尾\n".encode()


@pytest.mark.parametrize("content", ["", " \n", "bad\x00prompt"])
def test_creator_prompt_command_rejects_invalid_content(content: str) -> None:
    with pytest.raises(CreatorPromptViolation, match="CON-PROMPT-CONTENT"):
        CreatorPromptRevisionCommand(
            PromptKind.CREATOR_GUIDANCE,
            None,
            content,
            TraceId("1" * 32),
        )


def test_creator_prompt_command_enforces_utf8_byte_limit() -> None:
    with pytest.raises(CreatorPromptViolation, match="CON-PROMPT-CONTENT"):
        CreatorPromptRevisionCommand(
            PromptKind.CREATOR_GUIDANCE,
            None,
            "界" * (MAX_CREATOR_PROMPT_BYTES // 3 + 1),
            TraceId("1" * 32),
        )


def test_creator_prompt_command_rejects_non_text_without_leaking_type_error() -> None:
    with pytest.raises(CreatorPromptViolation, match="CON-PROMPT-CONTENT"):
        CreatorPromptRevisionCommand(
            PromptKind.CREATOR_GUIDANCE,
            None,
            cast(str, object()),
            TraceId("1" * 32),
        )


def test_creator_prompt_view_requires_a_complete_immutable_revision() -> None:
    content = "先核对事实，再形成判断。"  # noqa: RUF001
    revision_id = uuid7()
    view = CreatorPromptView(
        prompt_document_id=uuid7(),
        prompt_kind=PromptKind.CREATOR_GUIDANCE,
        status=PromptDocumentStatus.INACTIVE,
        current_revision_id=revision_id,
        revision_no=2,
        previous_revision_id=uuid7(),
        revision_kind=PromptRevisionKind.DEACTIVATED,
        content=content,
        activated_at=Instant(datetime.now(UTC)),
    )

    assert view.current_revision_id == revision_id
    assert view.status is PromptDocumentStatus.INACTIVE


def test_creator_prompt_view_carries_trusted_content_without_digest() -> None:
    view = CreatorPromptView(
        prompt_document_id=uuid7(),
        prompt_kind=PromptKind.CREATOR_GUIDANCE,
        status=PromptDocumentStatus.ACTIVE,
        current_revision_id=uuid7(),
        revision_no=1,
        previous_revision_id=None,
        revision_kind=PromptRevisionKind.CREATED,
        content="真实内容",
        activated_at=Instant(datetime.now(UTC)),
    )

    assert view.content == "真实内容"
