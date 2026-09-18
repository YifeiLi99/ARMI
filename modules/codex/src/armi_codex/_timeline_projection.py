"""Creator-visible projection of the private Codex task-source contract."""

from __future__ import annotations

import json
from typing import Any, cast

from armi_interaction.api import SceneTimelineCodexTaskProjectionPort
from armi_kernel.application import (
    ArtifactIntegrityStatus,
    ArtifactPrivacyScope,
    ArtifactRef,
)
from armi_kernel.contracts import Digest

_MAX_MANIFEST_BYTES = 64 * 1024
_MAX_OBJECTIVE_BYTES = 16 * 1024


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


class CodexTaskTimelineProjection(SceneTimelineCodexTaskProjectionPort):
    """Expose only the Creator-authored objective from a verified task source."""

    def objective(self, *, artifact: ArtifactRef, content: bytes) -> str:
        if (
            artifact.media_type != "application/json"
            or artifact.logical_kind != "codex.task-source-manifest"
            or artifact.privacy_scope is not ArtifactPrivacyScope.PRIVATE
            or artifact.integrity_status is not ArtifactIntegrityStatus.VERIFIED
            or type(content) is not bytes
            or not content
            or len(content) > _MAX_MANIFEST_BYTES
            or len(content) != artifact.byte_size
            or Digest.from_bytes(content) != artifact.content_digest
        ):
            raise ValueError("Codex task artifact is invalid")
        try:
            decoded = cast(
                object,
                json.loads(
                    content.decode("utf-8", errors="strict"),
                    object_pairs_hook=_strict_object,
                    parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
                ),
            )
            if type(decoded) is not dict:
                raise ValueError
            document = cast(dict[str, object], decoded)
            # Historical task records remain readable; execution validates its own contract.
            objective = document["objective"]
            if type(objective) is not str or "\x00" in objective:
                raise ValueError
            encoded = objective.encode("utf-8", errors="strict")
            if (
                not encoded
                or len(encoded) > _MAX_OBJECTIVE_BYTES
                or not any(not character.isspace() for character in objective)
            ):
                raise ValueError
            return objective
        except (
            KeyError,
            TypeError,
            UnicodeDecodeError,
            UnicodeEncodeError,
            ValueError,
            json.JSONDecodeError,
        ):
            raise ValueError("Codex task manifest is invalid") from None


__all__ = ("CodexTaskTimelineProjection",)
