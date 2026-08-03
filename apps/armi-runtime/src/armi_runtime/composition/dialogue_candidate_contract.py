"""Compact model output contract for ordinary Creator dialogue."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter

DIALOGUE_CANDIDATE_VERSION = "armi.creator-dialogue-candidate.v1"

Summary = Annotated[str, StringConstraints(min_length=1, max_length=512)]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class DialogueExperience(_StrictModel):
    first_person_gist: Annotated[
        str,
        StringConstraints(min_length=1, max_length=1024),
    ]
    uncertainty: Summary | None = None


class CreatorDialogueCandidate(_StrictModel):
    """A subjective dialogue choice; wire metadata belongs to the adapter."""

    @property
    def schema_version(self) -> str:
        return DIALOGUE_CANDIDATE_VERSION


class DialogueReplyDecision(CreatorDialogueCandidate):
    kind: Literal["reply"]
    content: Annotated[str, StringConstraints(min_length=1, max_length=65536)]
    experience: DialogueExperience | None = None


class DialogueTerminalDecision(CreatorDialogueCandidate):
    kind: Literal[
        "decline",
        "no_action",
        "no_change",
        "defer",
        "need_information",
    ]


DialogueDecision = Annotated[
    DialogueReplyDecision | DialogueTerminalDecision,
    Field(discriminator="kind"),
]

_ADAPTER: TypeAdapter[DialogueDecision] = TypeAdapter(DialogueDecision)


def dialogue_candidate_schema() -> dict[str, Any]:
    return _ADAPTER.json_schema()


def parse_dialogue_candidate(value: object) -> CreatorDialogueCandidate:
    return _ADAPTER.validate_python(value, strict=True)


__all__ = (
    "DIALOGUE_CANDIDATE_VERSION",
    "CreatorDialogueCandidate",
    "DialogueExperience",
    "DialogueReplyDecision",
    "DialogueTerminalDecision",
    "dialogue_candidate_schema",
    "parse_dialogue_candidate",
)
