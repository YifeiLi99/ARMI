"""Prompt invariants."""

from __future__ import annotations

import json
import re
from typing import Any, cast
from uuid import UUID

import rfc8785
from armi_kernel.application import CandidateFactClass

from .api import (
    MAX_CREATOR_PROMPT_BYTES,
    CandidatePromptDraft,
    CreatorPromptView,
    CreatorPromptViolation,
    PromptDocumentStatus,
    PromptKind,
    PromptRevisionKind,
    PromptViolation,
)

_REF = re.compile(r"^[a-z][a-z0-9_.-]{0,63}:[A-Za-z0-9_.:@/-]{1,191}$", re.ASCII)
_GROUP = re.compile(r"^group:[A-Za-z0-9_.:@/-]{1,191}$", re.ASCII)
_CONTENT_KEYS = {
    "schema_version",
    "cognition_method",
    "expression_method",
    "reflection_method",
}


def validate_candidate(value: CandidatePromptDraft) -> None:
    try:
        content = json.loads(value.content_bytes)
        if type(content) is not dict:
            raise ValueError
        document = cast(dict[str, object], content)
        valid_content = (
            set(document) == _CONTENT_KEYS
            and document["schema_version"] == "armi.subject-prompt.v1"
            and rfc8785.dumps(cast(Any, document)) == value.content_bytes
            and all(
                type(document[key]) is str
                and 1 <= len(cast(str, document[key])) <= 512
                and cast(str, document[key]).strip()
                and "\x00" not in cast(str, document[key])
                for key in (
                    "cognition_method",
                    "expression_method",
                    "reflection_method",
                )
            )
        )
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        valid_content = False
    if (
        _REF.fullmatch(value.proposal_ref) is None
        or _GROUP.fullmatch(value.atomic_group_ref) is None
        or not value.basis_ordinals
        or any(type(item) is not int or item < 1 for item in value.basis_ordinals)
        or len(set(value.basis_ordinals)) != len(value.basis_ordinals)
        or value.fact_class is not CandidateFactClass.SUBJECTIVE_UNDERSTANDING
        or type(value.prompt_document_id) is not UUID
        or value.prompt_document_id.version != 7
        or (
            value.current_revision_id is not None
            and (
                type(value.current_revision_id) is not UUID
                or value.current_revision_id.version != 7
            )
        )
        or type(value.expected_revision_no) is not int
        or value.expected_revision_no < 0
        or (value.current_revision_id is None) != (value.expected_revision_no == 0)
        or type(value.content_bytes) is not bytes
        or not value.content_bytes
        or len(value.content_bytes) > 16_384
        or not valid_content
    ):
        raise PromptViolation("PROMPT-CANDIDATE")


def validate_creator_view(value: CreatorPromptView) -> None:
    revision_values = (
        value.current_revision_id,
        value.revision_no,
        value.revision_kind,
        value.content,
        value.activated_at,
    )
    has_revision = value.current_revision_id is not None
    if (
        type(value.prompt_document_id) is not UUID
        or value.prompt_document_id.version != 7
        or value.prompt_kind is not PromptKind.CREATOR_GUIDANCE
        or type(value.status) is not PromptDocumentStatus
        or has_revision != all(item is not None for item in revision_values)
        or (not has_revision and value.status is not PromptDocumentStatus.ACTIVE)
        or (
            value.revision_kind is PromptRevisionKind.DEACTIVATED
            and value.status is not PromptDocumentStatus.INACTIVE
        )
        or (
            value.revision_kind in (PromptRevisionKind.CREATED, PromptRevisionKind.REVISED)
            and value.status is not PromptDocumentStatus.ACTIVE
        )
        or (
            value.current_revision_id is not None
            and value.current_revision_id.version != 7
        )
        or (
            value.previous_revision_id is not None
            and value.previous_revision_id.version != 7
        )
        or (
            value.revision_no is not None
            and (type(value.revision_no) is not int or value.revision_no < 1)
        )
        or (value.revision_no == 1 and value.previous_revision_id is not None)
        or (
            value.revision_no is not None
            and value.revision_no > 1
            and value.previous_revision_id is None
        )
    ):
        raise CreatorPromptViolation("CON-PROMPT-VIEW")
    if value.content is not None:
        try:
            encoded = value.content.encode("utf-8", errors="strict")
        except UnicodeError:
            raise CreatorPromptViolation("CON-PROMPT-VIEW") from None
        if (
            not value.content.strip()
            or "\x00" in value.content
            or not 1 <= len(encoded) <= MAX_CREATOR_PROMPT_BYTES
        ):
            raise CreatorPromptViolation("CON-PROMPT-VIEW")


__all__ = ("validate_candidate", "validate_creator_view")
