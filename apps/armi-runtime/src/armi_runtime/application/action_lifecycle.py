"""Runtime-only coordination for the multi-owner action lifecycle."""

from __future__ import annotations

from uuid import UUID

from armi_artifact_store.api import ArtifactCatalogPort
from armi_codex.api import CodexArtifactReadPort
from armi_effect.api import (
    EffectViolation,
)
from armi_kernel.application import ArtifactRef
from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWork


class RuntimeCodexArtifactReference:
    __slots__ = ("_artifacts", "_codex")

    def __init__(
        self,
        *,
        artifacts: ArtifactCatalogPort,
        codex: CodexArtifactReadPort,
    ) -> None:
        self._artifacts = artifacts
        self._codex = codex

    async def artifact_reference(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        effect_id: UUID,
        kind: str,
    ) -> ArtifactRef:
        artifact_id = await self._codex.artifact_ref(
            unit_of_work.transaction,
            effect_id=effect_id,
            kind=kind,
        )
        if artifact_id is None:
            raise EffectViolation("EFFECT-PAYLOAD-UNAVAILABLE")
        ref = await self._artifacts.retained_ref_in(
            unit_of_work.transaction,
            artifact_id,
        )
        if ref is None:
            raise EffectViolation("EFFECT-PAYLOAD-UNAVAILABLE")
        return ref


__all__ = ("RuntimeCodexArtifactReference",)
