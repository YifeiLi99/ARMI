"""Canonical owner-draft codec for Prompt."""

from __future__ import annotations

import json
from typing import Any, cast
from uuid import UUID

import rfc8785
from armi_kernel.application import CandidateFactClass, CandidateOwnerDraft

from .api import CandidatePromptDraft, PromptViolation

_KEYS = {
    "schema_version",
    "proposal_ref",
    "atomic_group_ref",
    "basis_ordinals",
    "fact_class",
    "prompt_document_id",
    "current_revision_id",
    "expected_revision_no",
    "content",
}


def encode(value: CandidatePromptDraft) -> bytes:
    return rfc8785.dumps(
        cast(
            Any,
            {
                "schema_version": "armi.prompt-candidate.v1",
                "proposal_ref": value.proposal_ref,
                "atomic_group_ref": value.atomic_group_ref,
                "basis_ordinals": list(value.basis_ordinals),
                "fact_class": value.fact_class.value,
                "prompt_document_id": str(value.prompt_document_id),
                "current_revision_id": (
                    None if value.current_revision_id is None else str(value.current_revision_id)
                ),
                "expected_revision_no": value.expected_revision_no,
                "content": json.loads(value.content_bytes),
            },
        )
    )


def decode(payload: bytes) -> CandidatePromptDraft:
    try:
        raw_value = cast(object, json.loads(payload))
        if type(raw_value) is not dict:
            raise ValueError
        raw = cast(dict[str, object], raw_value)
        ordinals = raw["basis_ordinals"]
        current = raw["current_revision_id"]
        if (
            set(raw) != _KEYS
            or raw["schema_version"] != "armi.prompt-candidate.v1"
            or rfc8785.dumps(cast(Any, raw)) != payload
            or type(ordinals) is not list
            or any(type(item) is not int for item in cast(list[object], ordinals))
            or type(raw["proposal_ref"]) is not str
            or type(raw["atomic_group_ref"]) is not str
            or type(raw["fact_class"]) is not str
            or type(raw["prompt_document_id"]) is not str
            or (current is not None and type(current) is not str)
            or type(raw["expected_revision_no"]) is not int
        ):
            raise ValueError
        return CandidatePromptDraft(
            raw["proposal_ref"],
            raw["atomic_group_ref"],
            tuple(cast(list[int], ordinals)),
            CandidateFactClass(raw["fact_class"]),
            UUID(raw["prompt_document_id"]),
            None if current is None else UUID(current),
            raw["expected_revision_no"],
            rfc8785.dumps(cast(Any, raw["content"])),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        raise PromptViolation("PROMPT-CODEC") from None


def decode_legacy(value: object) -> CandidatePromptDraft:
    try:
        if type(value) is not dict:
            raise ValueError
        item = cast(dict[str, object], value)
        content = item["content"]
        if type(content) is not dict:
            raise ValueError
        return CandidatePromptDraft(
            cast(str, item["proposal_ref"]),
            cast(str, item["atomic_group_ref"]),
            tuple(cast(list[int], item["basis_ordinals"])),
            CandidateFactClass(cast(str, item["fact_class"])),
            UUID(cast(str, item["prompt_document_id"])),
            (
                None
                if item["current_revision_id"] is None
                else UUID(cast(str, item["current_revision_id"]))
            ),
            cast(int, item["expected_revision_no"]),
            rfc8785.dumps(cast(Any, content)),
        )
    except (KeyError, TypeError, ValueError):
        raise PromptViolation("PROMPT-CODEC") from None


def bind(value: CandidatePromptDraft) -> CandidateOwnerDraft:
    return CandidateOwnerDraft(
        value.proposal_ref,
        value.atomic_group_ref,
        value.basis_ordinals,
        value.fact_class,
        "prompt",
        encode(value),
    )


__all__ = ("bind", "decode", "decode_legacy", "encode")
