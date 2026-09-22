"""Restricted candidate contract for one private visual observation."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from armi_kernel.contracts import NONBLANK_TEXT_PATTERN
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter

from ._focus.api import (
    ConcernChange,
)
from ._strict_model_json import strict_model_value

VISUAL_OBSERVATION_CANDIDATE_VERSION = "armi.visual-observation-candidate"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    @property
    def schema_kind(self) -> str:
        return VISUAL_OBSERVATION_CANDIDATE_VERSION


class VisualExperience(_StrictModel):
    first_person_gist: Annotated[
        str,
        StringConstraints(min_length=1, max_length=1024, pattern=NONBLANK_TEXT_PATTERN),
    ]
    fact_class: Literal["external_claim", "inference", "unknown"]
    uncertainty: (
        Annotated[
            str,
            StringConstraints(
                min_length=1, max_length=512, pattern=NONBLANK_TEXT_PATTERN
            ),
        ]
        | None
    ) = None


class IgnoreVisualObservation(_StrictModel):
    concern_changes: tuple[ConcernChange, ...] = Field(default=(), max_length=4)
    kind: Literal["ignore"]


class AcceptVisualExperience(_StrictModel):
    concern_changes: tuple[ConcernChange, ...] = Field(default=(), max_length=4)
    kind: Literal["experience"]
    experience: VisualExperience


VisualObservationCandidate = Annotated[
    IgnoreVisualObservation | AcceptVisualExperience,
    Field(discriminator="kind"),
]
_ADAPTER: TypeAdapter[VisualObservationCandidate] = TypeAdapter(
    VisualObservationCandidate
)


def visual_observation_candidate_schema() -> dict[str, Any]:
    return _ADAPTER.json_schema()


def parse_visual_observation_candidate(value: object) -> VisualObservationCandidate:
    return _ADAPTER.validate_python(strict_model_value(value), strict=True)


__all__ = (
    "VISUAL_OBSERVATION_CANDIDATE_VERSION",
    "AcceptVisualExperience",
    "IgnoreVisualObservation",
    "VisualExperience",
    "VisualObservationCandidate",
    "parse_visual_observation_candidate",
    "visual_observation_candidate_schema",
)
