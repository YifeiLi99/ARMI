"""Verify Creator-to-Codex lifecycle through production interfaces only."""

from __future__ import annotations

import argparse
import http.client
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


@dataclass(frozen=True, slots=True)
class _Lifecycle:
    task_source_id: str | None
    first_episode_status: str | None
    effect_id: str | None
    effect_status: str | None
    verification_id: str | None
    verification_status: str | None
    result_source_id: str | None
    second_episode_status: str | None
    second_commit_id: str | None
    experience_id: str | None


_LIFECYCLE_SQL = """
WITH task AS (
    SELECT source.codex_task_source_id FROM armi.codex_task_sources AS source
    WHERE source.trace_id=%s
), first_episode AS (
    SELECT episode.cognitive_episode_id,episode.status FROM task
    JOIN armi.external_evidence AS evidence
      ON evidence.codex_task_source_id=task.codex_task_source_id
    JOIN armi.opportunities AS opportunity ON opportunity.evidence_id=evidence.evidence_id
    JOIN armi.cognitive_episodes AS episode
      ON episode.opportunity_id=opportunity.opportunity_id
    ORDER BY episode.prepared_at NULLS LAST,episode.cognitive_episode_id LIMIT 1
), first_commit AS (
    SELECT commit.subject_commit_id FROM first_episode
    JOIN armi.subject_commits AS commit
      ON commit.cognitive_episode_id=first_episode.cognitive_episode_id
), effect AS (
    SELECT effect.effect_id,effect.status FROM task
    JOIN armi.action_intent_revisions AS revision
      ON revision.codex_task_source_id=task.codex_task_source_id
    JOIN armi.effects AS effect
      ON effect.action_intent_revision_id=revision.action_intent_revision_id
    ORDER BY effect.registered_at,effect.effect_id LIMIT 1
), verification AS (
    SELECT result.codex_verification_id,result.execution_status FROM effect
    JOIN armi.codex_verification_results AS result ON result.effect_id=effect.effect_id
), result_source AS (
    SELECT source.codex_result_source_id,source.evidence_id FROM verification
    JOIN armi.codex_result_sources AS source
      ON source.codex_verification_id=verification.codex_verification_id
), second_episode AS (
    SELECT episode.cognitive_episode_id,episode.status FROM result_source
    JOIN armi.opportunities AS opportunity
      ON opportunity.evidence_id=result_source.evidence_id
    JOIN armi.cognitive_episodes AS episode
      ON episode.opportunity_id=opportunity.opportunity_id
    ORDER BY episode.prepared_at NULLS LAST,episode.cognitive_episode_id LIMIT 1
), second_commit AS (
    SELECT commit.subject_commit_id FROM second_episode
    JOIN armi.subject_commits AS commit
      ON commit.cognitive_episode_id=second_episode.cognitive_episode_id
), experience AS (
    SELECT accepted.experience_id FROM result_source
    JOIN armi.experience_evidence_links AS link
      ON link.evidence_id=result_source.evidence_id
    JOIN armi.accepted_experiences AS accepted
      ON accepted.experience_id=link.experience_id
    ORDER BY accepted.experience_id LIMIT 1
)
SELECT
    (SELECT codex_task_source_id FROM task),(SELECT status FROM first_episode),
    (SELECT effect_id FROM effect),(SELECT status FROM effect),
    (SELECT codex_verification_id FROM verification),
    (SELECT execution_status FROM verification),
    (SELECT codex_result_source_id FROM result_source),(SELECT status FROM second_episode),
    (SELECT subject_commit_id FROM second_commit),(SELECT experience_id FROM experience)
"""


def _conninfo(environment_root: Path) -> str:
    prepared = prepare_environment(
        environment_root,
        credential_scope={"live.codex.delegation": "database.runtime"},
    )
    locator = prepared.effective.config.secret_locators["database.runtime"]
    with prepared.credential_port.resolve(
        locator, CredentialPurpose("live.codex.delegation")
    ) as handle:
        return handle.consume(lambda value: bytes(value).decode("utf-8"))


def _read(connection: psycopg.Connection[Any], trace_id: str) -> _Lifecycle:
    row = connection.execute(_LIFECYCLE_SQL, (trace_id,)).fetchone()
    if row is None:
        raise RuntimeError("LIVE-CODEX-STATE")

    def text(value: object) -> str | None:
        return None if value is None else str(value)

    return _Lifecycle(
        text(row[0]),
        text(row[1]),
        text(row[2]),
        text(row[3]),
        text(row[4]),
        text(row[5]),
        text(row[6]),
        text(row[7]),
        text(row[8]),
        text(row[9]),
    )


def _request(
    connection: http.client.HTTPConnection,
    method: str,
    path: str,
    *,
    headers: dict[str, str],
    body: dict[str, object] | None = None,
) -> tuple[int, dict[str, Any]]:
    encoded = None
    effective = dict(headers)
    if body is not None:
        encoded = json.dumps(body, separators=(",", ":")).encode("utf-8")
        effective.update(
            {"Content-Type": "application/json", "Content-Length": str(len(encoded))}
        )
    connection.request(method, path, body=encoded, headers=effective)
    response = connection.getresponse()
    return response.status, cast(dict[str, Any], json.loads(response.read()))


def verify(
    environment_root: Path,
    *,
    objective: str,
    model_id: str,
    reasoning_effort: str,
    timeout_seconds: float,
) -> dict[str, object]:
    prepared = prepare_environment(environment_root)
    port = prepared.effective.config.creator.port
    origin = f"http://127.0.0.1:{port}"
    boundary = {
        "Origin": origin,
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
    }
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
    try:
        status, session = _request(
            connection, "POST", "/v1/browser-sessions", headers=boundary
        )
        if status != 200:
            raise RuntimeError("LIVE-CODEX-SESSION")
        headers = {
            **boundary,
            "Authorization": f"Bearer {session['browser_session_token']}",
        }
        status, accepted = _request(
            connection,
            "POST",
            "/v1/scenes/default/codex-tasks",
            headers={**headers, "Idempotency-Key": f"live-codex-{uuid7()}"},
            body={
                "contract_version": "1.0",
                "objective": objective,
                "model_id": model_id,
                "reasoning_effort": reasoning_effort,
                "web_search": False,
            },
        )
        if status != 202:
            raise RuntimeError("LIVE-CODEX-INTAKE")
        trace_id = str(accepted["trace_id"])
        deadline = time.monotonic() + timeout_seconds
        last = _Lifecycle(*((None,) * 10))
        with psycopg.connect(_conninfo(prepared.root), autocommit=True) as database:
            while time.monotonic() < deadline:
                last = _read(database, trace_id)
                if last.effect_status in {"failed", "unknown", "cancelled"}:
                    raise RuntimeError(
                        f"LIVE-CODEX-EFFECT-{last.effect_status.upper()}"
                    )
                if last.verification_status in {"failed", "unknown", "cancelled"}:
                    raise RuntimeError(
                        f"LIVE-CODEX-VERIFICATION-{last.verification_status.upper()}"
                    )
                if (
                    last.effect_status == "completed"
                    and last.verification_status == "verified"
                    and last.result_source_id is not None
                    and last.second_episode_status == "completed"
                    and last.second_commit_id is not None
                    and last.experience_id is not None
                ):
                    return {
                        "status": "passed",
                        "trace_id": trace_id,
                        "operation_ref": accepted["result_ref"],
                        "task_source_id": last.task_source_id,
                        "effect_id": last.effect_id,
                        "verification_id": last.verification_id,
                        "result_source_id": last.result_source_id,
                        "second_commit_id": last.second_commit_id,
                        "experience_id": last.experience_id,
                    }
                time.sleep(0.25)
        raise RuntimeError(f"LIVE-CODEX-TIMEOUT:{last}")
    finally:
        connection.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment-root", type=Path, required=True)
    parser.add_argument(
        "--objective",
        default="Create result.md containing exactly: ARMI Codex lifecycle verified",
    )
    parser.add_argument(
        "--model-id",
        choices=("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"),
        default="gpt-5.6-terra",
    )
    parser.add_argument(
        "--reasoning-effort",
        choices=("low", "medium", "high", "xhigh", "max"),
        default="medium",
    )
    parser.add_argument("--timeout-seconds", type=float, default=600.0)
    args = parser.parse_args(argv)
    if not 30 <= args.timeout_seconds <= 1800:
        parser.error("--timeout-seconds must be between 30 and 1800")
    try:
        result = verify(
            args.environment_root.resolve(),
            objective=cast(str, args.objective),
            model_id=cast(str, args.model_id),
            reasoning_effort=cast(str, args.reasoning_effort),
            timeout_seconds=cast(float, args.timeout_seconds),
        )
    except (KeyError, OSError, RuntimeError, psycopg.Error) as error:
        print(
            json.dumps(
                {"status": "failed", "reason": str(error)},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
