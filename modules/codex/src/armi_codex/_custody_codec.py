"""Binary custody envelope for the supervised one-shot Codex runner."""

from __future__ import annotations

import struct

from ._codec import decode_result, encode_result
from ._runner import CodexRunArtifactSet
from ._runner_contract import CodexRunnerViolation, CodexRunResult

_MAGIC = b"ARMI-CODEX-CUSTODY-V1\n"
_ARTIFACT_NAMES = (
    "event_transcript",
    "final_result",
    "patch",
    "result_bundle",
    "diagnostics",
    "validation_report",
)
_MAX_RESULT_BYTES = 64 * 1024
_MAX_ARTIFACT_BYTES = 100 * 1024 * 1024
_MAX_ENVELOPE_BYTES = 512 * 1024 * 1024


def encode_custodied_result(
    result: CodexRunResult,
    artifacts: CodexRunArtifactSet,
) -> bytes:
    result_bytes = encode_result(result)
    if len(result_bytes) > _MAX_RESULT_BYTES:
        raise CodexRunnerViolation("CODEX-RESULT-FORMAT")
    output = bytearray(_MAGIC)
    output.extend(struct.pack(">I", len(result_bytes)))
    output.extend(result_bytes)
    for name in _ARTIFACT_NAMES:
        value = getattr(artifacts, name)
        if type(value) is not bytes or len(value) > _MAX_ARTIFACT_BYTES:
            raise CodexRunnerViolation("CODEX-OUTPUT-LIMIT")
        output.extend(struct.pack(">Q", len(value)))
        output.extend(value)
    if len(output) > _MAX_ENVELOPE_BYTES:
        raise CodexRunnerViolation("CODEX-OUTPUT-LIMIT")
    return bytes(output)


def decode_custodied_result(
    value: bytes,
) -> tuple[CodexRunResult, CodexRunArtifactSet]:
    if (
        type(value) is not bytes
        or not value.startswith(_MAGIC)
        or len(value) > _MAX_ENVELOPE_BYTES
    ):
        raise CodexRunnerViolation("CODEX-RESULT-FORMAT")
    offset = len(_MAGIC)
    result_length, offset = _length(value, offset, 4, _MAX_RESULT_BYTES)
    result = decode_result(value[offset : offset + result_length])
    offset += result_length
    artifacts: dict[str, bytes] = {}
    for name in _ARTIFACT_NAMES:
        artifact_length, offset = _length(value, offset, 8, _MAX_ARTIFACT_BYTES)
        artifacts[name] = value[offset : offset + artifact_length]
        offset += artifact_length
    if offset != len(value):
        raise CodexRunnerViolation("CODEX-RESULT-FORMAT")
    return result, CodexRunArtifactSet(**artifacts)


def _length(value: bytes, offset: int, width: int, maximum: int) -> tuple[int, int]:
    if offset + width > len(value):
        raise CodexRunnerViolation("CODEX-RESULT-FORMAT")
    length = int.from_bytes(value[offset : offset + width], "big")
    offset += width
    if length > maximum or offset + length > len(value):
        raise CodexRunnerViolation("CODEX-RESULT-FORMAT")
    return length, offset


__all__ = ("decode_custodied_result", "encode_custodied_result")
