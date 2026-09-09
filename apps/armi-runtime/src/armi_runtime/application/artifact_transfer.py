"""Bounded transfer of an already governed Creator-visible artifact."""

from pydantic import BaseModel, ConfigDict, Field


class ArtifactReadWindow(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    offset: int = Field(default=0, ge=0)
    length: int = Field(default=65536, ge=1, le=1048576)


class ArtifactChunk(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    offset: int = Field(ge=0)
    byte_count: int = Field(ge=0, le=1048576)
    total_bytes: int = Field(ge=0)
    digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    next_offset: int | None


__all__ = ("ArtifactChunk", "ArtifactReadWindow")
