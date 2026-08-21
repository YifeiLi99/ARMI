"""Verify one real Creator input-to-reply round trip against a running ARMI."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from uuid import uuid7

import psycopg
from armi_kernel.application import CredentialPurpose
from armi_runtime.composition.environment import prepare_environment
from armi_runtime.composition.runtime_process import RuntimeProcessManager


@dataclass(frozen=True, slots=True)
class _RoundTripState:
    episode_id: str | None
    episode_status: str | None
    failure_code: str | None
    effect_id: str | None
    effect_status: str | None
    verification_status: str | None
    delivery_status: str | None
    storage_locator: str | None
    content_digest: str | None
    byte_size: int | None
    media_type: str | None
    integrity_status: str | None


_STATE_SQL = """
SELECT episode.cognitive_episode_id,
       episode.status,
       episode.failure_code,
       effect.effect_id,
       effect.status,
       effect.verification_status,
       outbox.status,
       artifact.storage_locator,
       artifact.content_digest,
       artifact.byte_size,
       artifact.media_type,
       artifact.integrity_status
FROM armi.party_input_interactions AS interaction
LEFT JOIN armi.cognitive_episodes AS episode
  ON episode.trace_id=interaction.trace_id
LEFT JOIN armi.effects AS effect
  ON effect.trace_id=interaction.trace_id
 AND effect.effect_kind='creator_response'
LEFT JOIN armi.effect_outbox_items AS outbox
  ON outbox.effect_id=effect.effect_id
LEFT JOIN armi.artifacts AS artifact
  ON artifact.artifact_id=effect.payload_artifact_id
WHERE interaction.interaction_id=%s
ORDER BY effect.registered_at DESC NULLS LAST
LIMIT 1
"""


def _runtime_conninfo(environment_root: Path) -> str:
    prepared = prepare_environment(
        environment_root,
        credential_scope={"creator.roundtrip": "database.runtime"},
    )
    locator = prepared.effective.config.secret_locators["database.runtime"]
    with prepared.credential_port.resolve(
        locator,
        CredentialPurpose("creator.roundtrip"),
    ) as handle:
        return handle.consume(lambda value: bytes(value).decode("utf-8"))


def _read_state(
    connection: psycopg.Connection[Any], interaction_id: str
) -> _RoundTripState:
    row = connection.execute(_STATE_SQL, (interaction_id,)).fetchone()
    if row is None:
        raise RuntimeError("LIVE-CREATOR-INTERACTION-MISSING")
    return _RoundTripState(
        episode_id=None if row[0] is None else str(row[0]),
        episode_status=None if row[1] is None else str(row[1]),
        failure_code=None if row[2] is None else str(row[2]),
        effect_id=None if row[3] is None else str(row[3]),
        effect_status=None if row[4] is None else str(row[4]),
        verification_status=None if row[5] is None else str(row[5]),
        delivery_status=None if row[6] is None else str(row[6]),
        storage_locator=None if row[7] is None else str(row[7]),
        content_digest=None if row[8] is None else str(row[8]),
        byte_size=None if row[9] is None else int(row[9]),
        media_type=None if row[10] is None else str(row[10]),
        integrity_status=None if row[11] is None else str(row[11]),
    )


def _verified_reply(environment_root: Path, state: _RoundTripState) -> str:
    if (
        state.storage_locator is None
        or state.content_digest is None
        or state.byte_size is None
        or state.media_type != "text/plain"
        or state.integrity_status != "verified"
    ):
        raise RuntimeError("LIVE-CREATOR-REPLY-ARTIFACT")
    artifact_root = (environment_root / "data" / "artifacts").resolve(strict=True)
    artifact_path = (artifact_root / state.storage_locator).resolve(strict=True)
    if not artifact_path.is_relative_to(artifact_root) or artifact_path.is_symlink():
        raise RuntimeError("LIVE-CREATOR-REPLY-ARTIFACT-PATH")
    content = artifact_path.read_bytes()
    if len(content) != state.byte_size:
        raise RuntimeError("LIVE-CREATOR-REPLY-SIZE")
    digest = f"sha256:{hashlib.sha256(content).hexdigest()}"
    if digest != state.content_digest:
        raise RuntimeError("LIVE-CREATOR-REPLY-DIGEST")
    try:
        reply = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise RuntimeError("LIVE-CREATOR-REPLY-UTF8") from error
    if not reply.strip():
        raise RuntimeError("LIVE-CREATOR-REPLY-EMPTY")
    return reply


def verify_roundtrip(
    environment_root: Path,
    *,
    message: str,
    timeout_seconds: float,
) -> dict[str, object]:
    prepared = prepare_environment(environment_root)
    runtime = RuntimeProcessManager(
        prepared.root,
        str(prepared.effective.config.environment.environment_id),
    )
    idempotency_key = f"live-roundtrip-{uuid7()}"
    accepted = runtime.send_creator_input(
        message,
        idempotency_key=idempotency_key,
    )
    interaction_id = str(accepted["interaction_id"])
    deadline = time.monotonic() + timeout_seconds
    last_state: _RoundTripState | None = None
    with psycopg.connect(
        _runtime_conninfo(prepared.root), autocommit=True
    ) as connection:
        while time.monotonic() < deadline:
            last_state = _read_state(connection, interaction_id)
            if last_state.episode_status == "failed":
                raise RuntimeError(
                    last_state.failure_code or "LIVE-CREATOR-EPISODE-FAILED"
                )
            if (
                last_state.episode_status == "completed"
                and last_state.effect_status == "completed"
                and last_state.verification_status == "verified"
                and last_state.delivery_status == "delivered"
            ):
                reply = _verified_reply(prepared.root, last_state)
                return {
                    "status": "passed",
                    "interaction_id": interaction_id,
                    "episode_id": last_state.episode_id,
                    "effect_id": last_state.effect_id,
                    "reply": reply,
                }
            time.sleep(0.25)
    failure = (
        "unobserved"
        if last_state is None
        else "/".join(
            value or "pending"
            for value in (
                last_state.episode_status,
                last_state.effect_status,
                last_state.verification_status,
                last_state.delivery_status,
            )
        )
    )
    raise RuntimeError(f"LIVE-CREATOR-TIMEOUT:{failure}")


def main(argv: Sequence[str] | None = None) -> int:
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment-root", type=Path, required=True)
    parser.add_argument(
        "--message",
        default="这是一次系统连通性测试。请简短回复, 表示你已经收到。",
    )
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    args = parser.parse_args(argv)
    if not 1.0 <= args.timeout_seconds <= 300.0:
        parser.error("--timeout-seconds must be between 1 and 300")
    try:
        result = verify_roundtrip(
            args.environment_root,
            message=cast(str, args.message),
            timeout_seconds=cast(float, args.timeout_seconds),
        )
    except (KeyError, OSError, RuntimeError, psycopg.Error) as error:
        print(
            json.dumps(
                {"status": "failed", "reason": str(error)},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 1
    print(
        json.dumps(
            result,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
