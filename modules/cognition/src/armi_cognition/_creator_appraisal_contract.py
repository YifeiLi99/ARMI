"""Shared semantic appraisal shapes for cognitive-act contracts."""

from __future__ import annotations

from typing import Annotated

from armi_kernel.contracts import NONBLANK_TEXT_PATTERN
from pydantic import BaseModel, ConfigDict, StringConstraints

from ._dialogue_contract import Summary


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class CreatorAppraisalExperience(_StrictModel):
    first_person_gist: Annotated[
        str,
        StringConstraints(min_length=1, max_length=1024, pattern=NONBLANK_TEXT_PATTERN),
    ]
    uncertainty: Summary | None = None
    memory_summary: Summary | None = None

    @property
    def remember(self) -> bool:
        return self.memory_summary is not None


__all__ = ("CreatorAppraisalExperience",)
