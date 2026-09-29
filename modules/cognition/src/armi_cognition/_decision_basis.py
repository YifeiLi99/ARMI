"""Structured grounds for a bounded choice, never generated subject content."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ._dialogue_contract import ContextRef


class DecisionBasis(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    reason_code: Literal[
        "sleep_window",
        "memory_retention",
        "no_maintenance_needed",
        "no_reflection_needed",
        "no_observation_needed",
        "existing_task",
    ]
    basis_refs: tuple[ContextRef, ...] = Field(min_length=1, max_length=8)
