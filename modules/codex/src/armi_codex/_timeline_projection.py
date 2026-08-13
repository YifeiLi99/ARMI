"""Creator-visible projection of the private Codex task-source contract."""

from __future__ import annotations

import json
from typing import Any, cast

import rfc8785
from armi_interaction.api import SceneTimelineCodexTaskProjectionPort
from armi_kernel.application import (
    ArtifactIntegrityStatus,
    ArtifactPrivacyScope,
    ArtifactRef,
)
from armi_kernel.contracts import Digest

_BASE_KEYS = frozenset(
    {
        "schema_version",
        "objective",
        "facts",
        "allowed_paths",
        "forbidden_paths",
        "validator_id",
        "deadline_seconds",
        "source_tree_digest",
    }
)
_V2_KEYS = _BASE_KEYS | {
    "model_id",
    "reasoning_effort",
    "web_search",
}
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
            version = document.get("schema_version")
            expected: frozenset[str]
            if version == "armi.codex-task-source.v2":
                expected = _V2_KEYS
            elif version == "armi.codex-task-source.v1":
                expected = _BASE_KEYS
            else:
                raise ValueError
            if frozenset(document) != expected:
                raise ValueError
            if rfc8785.dumps(cast(Any, document)) != content:
                raise ValueError
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
            if version == "armi.codex-task-source.v2" and (
                type(document["model_id"]) is not str
                or type(document["reasoning_effort"]) is not str
                or type(document["web_search"]) is not bool
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
