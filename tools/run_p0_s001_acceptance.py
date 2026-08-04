"""Run the isolated P0-S001 autonomous Activity acceptance."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from uuid import uuid7

import psycopg
import rfc8785
from armi_runtime.adapters.persistence.role_policy import physical_role_name
from armi_runtime.composition.birth_manifest import packaged_birth_digests
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo


class AcceptanceFailure(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _write_secret(path: Path, value: str) -> None:
    path.write_text(value, encoding="utf-8", newline="\n")


def _run(command: tuple[str, ...], *, cwd: Path) -> None:
    completed = subprocess.run(
        command,
        cwd=cwd,
        check=False,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise AcceptanceFailure("P0-ACC-SETUP")


def _start_runtime(executable: Path, root: Path, *, cwd: Path) -> subprocess.Popen[str]:
    return subprocess.Popen(
        (
            str(executable),
            "runtime",
            "start",
            "--environment-root",
            str(root),
        ),
        cwd=cwd,
        env={
            key: value
            for key, value in os.environ.items()
            if not key.startswith("ARMI_")
        },
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )


def _wait_listening(process: subprocess.Popen[str], port: int) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AcceptanceFailure("P0-ACC-RUNTIME-START")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.05)
    raise AcceptanceFailure("P0-ACC-RUNTIME-START")


def _stop_runtime(process: subprocess.Popen[str]) -> None:
    if process.poll() is None:
        process.send_signal(signal.CTRL_BREAK_EVENT)
        try:
            process.communicate(timeout=35)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            raise AcceptanceFailure("P0-ACC-RUNTIME-STOP") from None
    if process.returncode != 0:
        raise AcceptanceFailure("P0-ACC-RUNTIME-STOP")


def _projection(connection: psycopg.Connection[Any]) -> dict[str, Any]:
    row = connection.execute(
        """
        SELECT
            (SELECT count(*) FROM armi.opportunities
             WHERE source_kind = 'life_generation_available'),
            (SELECT count(*) FROM armi.cognitive_episodes
             WHERE purpose = 'consider_autonomous_life'),
            (SELECT count(*) FROM armi.cognitive_attempts AS attempt
             JOIN armi.cognitive_episodes AS episode
               ON episode.cognitive_episode_id = attempt.cognitive_episode_id
             WHERE episode.purpose = 'consider_autonomous_life'),
            (SELECT count(*) FROM armi.activities),
            (SELECT count(*) FROM armi.activity_revisions),
            (SELECT COALESCE(sum(attempt.estimated_cost_microyuan), 0)
             FROM armi.cognitive_attempts AS attempt
             JOIN armi.cognitive_episodes AS episode
               ON episode.cognitive_episode_id = attempt.cognitive_episode_id
             WHERE episode.purpose = 'consider_autonomous_life'),
            (SELECT count(*) FROM armi.opportunities
             WHERE purpose = 'consider_activity_attention'),
            (SELECT count(*) FROM armi.cognitive_episodes
             WHERE purpose = 'consider_activity_attention'),
            (SELECT count(*) FROM armi.cognitive_attempts AS attempt
             JOIN armi.cognitive_episodes AS episode
               ON episode.cognitive_episode_id = attempt.cognitive_episode_id
             WHERE episode.purpose = 'consider_activity_attention'),
            (SELECT count(*) FROM armi.activity_attention_decisions),
            (SELECT COALESCE(sum(attempt.estimated_cost_microyuan), 0)
             FROM armi.cognitive_attempts AS attempt
             JOIN armi.cognitive_episodes AS episode
               ON episode.cognitive_episode_id = attempt.cognitive_episode_id
             WHERE episode.purpose = 'consider_activity_attention')
        """
    ).fetchone()
    assert row is not None
    activity = connection.execute(
        """
        SELECT activity.activity_id, activity.current_revision_id,
               activity.head_version, activity.origin_opportunity_id,
               revision.status, revision.revision_no,
               encode(sha256(convert_to(revision.goal, 'UTF8')), 'hex'),
               encode(sha256(convert_to(revision.next_safe_step, 'UTF8')), 'hex')
        FROM armi.activities AS activity
        JOIN armi.activity_revisions AS revision
          ON revision.activity_revision_id = activity.current_revision_id
        ORDER BY activity.activity_id
        LIMIT 1
        """
    ).fetchone()
    model = connection.execute(
        """
        SELECT attempt.result_status, attempt.provider_model_id,
               attempt.input_tokens, attempt.output_tokens,
               attempt.cached_input_tokens, attempt.estimated_cost_microyuan
        FROM armi.cognitive_attempts AS attempt
        JOIN armi.cognitive_episodes AS episode
          ON episode.cognitive_episode_id = attempt.cognitive_episode_id
        WHERE episode.purpose = 'consider_autonomous_life'
        ORDER BY attempt.attempt_no DESC
        LIMIT 1
        """
    ).fetchone()
    episode = connection.execute(
        """
        SELECT status, final_disposition, application_resolution, failure_code
        FROM armi.cognitive_episodes
        WHERE purpose = 'consider_autonomous_life'
        ORDER BY created_at DESC
        LIMIT 1
        """
    ).fetchone()
    attention = connection.execute(
        """
        SELECT decision.decision_kind, decision.expected_revision_id,
               decision.expected_head_version, decision.result_revision_id,
               decision.resource_snapshot_digest,
               CASE WHEN decision.review_not_before IS NULL THEN false ELSE true END,
               application.resolution
        FROM armi.activity_attention_decisions AS decision
        JOIN armi.cognitive_candidate_applications AS application
          ON application.candidate_application_id = decision.candidate_application_id
        ORDER BY decision.decided_at DESC LIMIT 1
        """
    ).fetchone()
    return {
        "root_opportunity_count": int(row[0]),
        "episode_count": int(row[1]),
        "model_attempt_count": int(row[2]),
        "activity_count": int(row[3]),
        "activity_revision_count": int(row[4]),
        "estimated_cost_microyuan": int(row[5]),
        "attention_opportunity_count": int(row[6]),
        "attention_episode_count": int(row[7]),
        "attention_model_attempt_count": int(row[8]),
        "attention_decision_count": int(row[9]),
        "attention_estimated_cost_microyuan": int(row[10]),
        "activity": None
        if activity is None
        else {
            "activity_id": str(activity[0]),
            "current_revision_id": str(activity[1]),
            "head_version": int(activity[2]),
            "origin_opportunity_id": str(activity[3]),
            "status": str(activity[4]),
            "revision_no": int(activity[5]),
            "goal_sha256": f"sha256:{activity[6]}",
            "next_step_sha256": f"sha256:{activity[7]}",
        },
        "model": None
        if model is None
        else {
            "result_status": model[0],
            "provider_model_id": model[1],
            "input_tokens": model[2],
            "output_tokens": model[3],
            "cached_input_tokens": model[4],
            "estimated_cost_microyuan": model[5],
        },
        "episode": None
        if episode is None
        else {
            "status": episode[0],
            "final_disposition": episode[1],
            "application_resolution": episode[2],
            "failure_code": episode[3],
        },
        "attention": None
        if attention is None
        else {
            "decision_kind": str(attention[0]),
            "expected_revision_id": str(attention[1]),
            "expected_head_version": int(attention[2]),
            "result_revision_id": (None if attention[3] is None else str(attention[3])),
            "resource_snapshot_digest": str(attention[4]),
            "has_review_not_before": bool(attention[5]),
            "application_resolution": str(attention[6]),
        },
    }


def _wait_activity(dsn: str) -> dict[str, Any]:
    deadline = time.monotonic() + 180
    latest: dict[str, Any] = {}
    while time.monotonic() < deadline:
        with psycopg.connect(dsn) as connection:
            latest = _projection(connection)
            disposition = connection.execute(
                """
                SELECT opportunity.current_disposition,
                       episode.application_resolution
                FROM armi.opportunities AS opportunity
                LEFT JOIN armi.cognitive_episodes AS episode
                  ON episode.opportunity_id = opportunity.opportunity_id
                WHERE opportunity.source_kind = 'life_generation_available'
                """
            ).fetchone()
        if latest.get("activity_count") == 1:
            return latest
        if disposition is not None and disposition[0] == "resolved":
            code = {
                "no_change": "P0-ACC-NO-ACTIVITY",
                "deferred": "P0-ACC-DEFERRED",
                "need_information": "P0-ACC-NEED-INFORMATION",
            }.get(disposition[1], "P0-ACC-NO-ACTIVITY")
            raise AcceptanceFailure(code)
        time.sleep(0.25)
    raise AcceptanceFailure("P0-ACC-TIMEOUT")


def _wait_attention(dsn: str) -> dict[str, Any]:
    deadline = time.monotonic() + 180
    latest: dict[str, Any] = {}
    while time.monotonic() < deadline:
        with psycopg.connect(dsn) as connection:
            latest = _projection(connection)
            failed = connection.execute(
                """
                SELECT status, failure_code
                FROM armi.cognitive_episodes
                WHERE purpose = 'consider_activity_attention'
                ORDER BY created_at DESC LIMIT 1
                """
            ).fetchone()
        if latest.get("attention_decision_count") == 1:
            return latest
        if failed is not None and failed[0] in {"failed", "cancelled", "stale"}:
            raise AcceptanceFailure("P0-ACC-ATTENTION-FAILED")
        time.sleep(0.25)
    raise AcceptanceFailure("P0-ACC-ATTENTION-TIMEOUT")


def _sha256(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provisioner-conninfo-file", type=Path, required=True)
    parser.add_argument("--ark-api-key-file", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--s002-evidence", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    root = args.root.resolve()
    executable = (root / ".venv/Scripts/armi.exe").resolve()
    environment_id = uuid7()
    database = f"p0s001_{secrets.token_hex(6)}"
    roles = tuple(
        physical_role_name(environment_id, role)
        for role in ("runtime", "admin", "migrator")
    )
    provisioner = args.provisioner_conninfo_file.read_text(encoding="utf-8").strip()
    ark_key = args.ark_api_key_file.read_text(encoding="utf-8").strip()
    if not provisioner or not ark_key:
        print(json.dumps({"code": "P0-ACC-CREDENTIAL", "status": "rejected"}))
        return 2
    admin_values = conninfo_to_dict(provisioner)
    database_dsn = make_conninfo(**{**admin_values, "dbname": database})
    created = False
    process: subprocess.Popen[str] | None = None
    work: Path | None = None
    try:
        with psycopg.connect(provisioner, autocommit=True) as connection:
            connection.execute(
                sql.SQL(
                    "CREATE DATABASE {} TEMPLATE template0 ENCODING 'UTF8' "
                    "LOCALE_PROVIDER builtin BUILTIN_LOCALE 'C.UTF-8'"
                ).format(sql.Identifier(database))
            )
        created = True
        with tempfile.TemporaryDirectory(
            prefix="p0-s001-", dir=root / ".tmp", delete=False
        ) as temp:
            work = Path(temp).resolve()
            secrets_root = work / "secrets"
            data_root = work / "data"
            bootstrap = work / "bootstrap"
            for path in (secrets_root, data_root, bootstrap):
                path.mkdir()
            passwords = {
                role: secrets.token_urlsafe(32)
                for role in ("runtime", "admin", "migrator")
            }
            _write_secret(secrets_root / "provisioner", database_dsn)
            for role, password in passwords.items():
                _write_secret(secrets_root / f"{role}-password", password)
            _run(
                (
                    sys.executable,
                    "-B",
                    "tools/bootstrap_database_roles.py",
                    "--environment-id",
                    str(environment_id),
                    "--secret-root",
                    str(secrets_root),
                    "--provisioner-conninfo-file",
                    str(secrets_root / "provisioner"),
                    "--runtime-password-file",
                    str(secrets_root / "runtime-password"),
                    "--admin-password-file",
                    str(secrets_root / "admin-password"),
                    "--migrator-password-file",
                    str(secrets_root / "migrator-password"),
                    "--apply",
                ),
                cwd=root,
            )
            common = {
                "host": str(admin_values["host"]),
                "port": str(admin_values["port"]),
            }
            runtime_dsn = make_conninfo(
                **common,
                dbname=database,
                user=roles[0],
                password=passwords["runtime"],
            )
            migrator_dsn = make_conninfo(
                **common,
                dbname=database,
                user=roles[2],
                password=passwords["migrator"],
            )
            _write_secret(secrets_root / "database-runtime", runtime_dsn)
            _write_secret(secrets_root / "database-migrator", migrator_dsn)
            _write_secret(
                secrets_root / "creator-bearer",
                "creator-v1." + secrets.token_urlsafe(32),
            )
            _write_secret(secrets_root / "ark-api-key", ark_key)
            port = _port()
            environment_toml = "\n".join(
                (
                    "[environment]",
                    f'environment_id = "{environment_id}"',
                    f'data_root = "{data_root.as_posix()}"',
                    "",
                    "[creator]",
                    f"port = {port}",
                    "",
                    "[secret_locators]",
                    f'"database.runtime" = "file:{(secrets_root / "database-runtime").as_posix()}"',
                    f'"database.migrator" = "file:{(secrets_root / "database-migrator").as_posix()}"',
                    f'"creator.bearer" = "file:{(secrets_root / "creator-bearer").as_posix()}"',
                    f'"model.ark_api_key" = "file:{(secrets_root / "ark-api-key").as_posix()}"',
                    "",
                )
            )
            (work / "environment.toml").write_text(
                environment_toml, encoding="utf-8", newline="\n"
            )
            packaged = packaged_birth_digests()
            anchor = {
                "schema_version": "armi.personality-anchor.v1",
                "voice_style": "约 16 岁少女口吻",
                "traits": ["好奇", "自主"],
            }
            birth = {
                "schema_version": "armi.birth-manifest.v1",
                "environment_id": str(environment_id),
                "birth_request_id": str(uuid7()),
                "creator_party_id": str(uuid7()),
                "idempotency_key": "p0-s001-formal-acceptance",
                "personality_anchor": anchor,
                "personality_anchor_digest": _sha256(rfc8785.dumps(anchor)),
                "expected_package": {
                    key: value.value for key, value in packaged.items()
                },
            }
            (bootstrap / "birth-manifest.json").write_bytes(
                rfc8785.dumps(birth) + b"\n"
            )
            _run(
                (str(executable), "db", "upgrade", "--environment-root", str(work)),
                cwd=root,
            )
            _run(
                (
                    str(executable),
                    "bootstrap",
                    "birth",
                    "--environment-root",
                    str(work),
                ),
                cwd=root,
            )
            process = _start_runtime(executable, work, cwd=root)
            _wait_listening(process, port)
            before = _wait_activity(database_dsn)
            if before["estimated_cost_microyuan"] > 2_000_000:
                raise AcceptanceFailure("P0-ACC-BUDGET")
            activity = before["activity"]
            if activity is None or activity["status"] != "ready":
                raise AcceptanceFailure("P0-ACC-ACTIVITY")
            before = _wait_attention(database_dsn)
            if before["attention_estimated_cost_microyuan"] > 2_000_000:
                raise AcceptanceFailure("P0-ACC-ATTENTION-BUDGET")
            if (
                before["estimated_cost_microyuan"]
                + before["attention_estimated_cost_microyuan"]
                > 4_000_000
            ):
                raise AcceptanceFailure("P0-ACC-TOTAL-BUDGET")
            if before["attention"] is None:
                raise AcceptanceFailure("P0-ACC-ATTENTION")
            _stop_runtime(process)
            process = None
            restarted = _start_runtime(executable, work, cwd=root)
            process = restarted
            _wait_listening(restarted, port)
            time.sleep(2)
            _stop_runtime(restarted)
            process = None
            with psycopg.connect(database_dsn) as connection:
                after = _projection(connection)
            if before != after:
                raise AcceptanceFailure("P0-ACC-RESTART-DRIFT")
            evidence = {
                "schema_version": "armi.p0-s001-evidence.v1",
                "source_revision": subprocess.run(
                    ("git", "rev-parse", "HEAD"),
                    cwd=root,
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.strip(),
                "schema_target": 29,
                "composition_digest": packaged["composition_digest"].value,
                "source": {
                    "kind": "life_generation_available",
                    "root_opportunity_count": before["root_opportunity_count"],
                },
                "projection": before,
                "restart_projection": after,
                "cleanup": {
                    "database": "pending",
                    "roles": "pending",
                    "runtime": "stopped",
                },
            }
            evidence_bytes = rfc8785.dumps(evidence) + b"\n"
            args.evidence.resolve().parent.mkdir(parents=True, exist_ok=True)
            args.evidence.resolve().write_bytes(evidence_bytes)
            s002_evidence = {
                "schema_version": "armi.p0-s002-evidence.v1",
                "source_revision": evidence["source_revision"],
                "schema_target": 29,
                "composition_digest": packaged["composition_digest"].value,
                "result": {"status": "pass"},
                "projection": {
                    "opportunity_count": before["attention_opportunity_count"],
                    "episode_count": before["attention_episode_count"],
                    "model_attempt_count": before["attention_model_attempt_count"],
                    "decision_count": before["attention_decision_count"],
                    "estimated_cost_microyuan": before[
                        "attention_estimated_cost_microyuan"
                    ],
                    "decision": before["attention"],
                    "activity": before["activity"],
                },
                "restart_projection": {
                    "opportunity_count": after["attention_opportunity_count"],
                    "episode_count": after["attention_episode_count"],
                    "model_attempt_count": after["attention_model_attempt_count"],
                    "decision_count": after["attention_decision_count"],
                    "decision": after["attention"],
                    "activity": after["activity"],
                },
                "cleanup": {
                    "database": "pending",
                    "roles": "pending",
                    "runtime": "stopped",
                },
            }
            args.s002_evidence.resolve().parent.mkdir(parents=True, exist_ok=True)
            args.s002_evidence.resolve().write_bytes(
                rfc8785.dumps(s002_evidence) + b"\n"
            )
        status = "pass"
    except AcceptanceFailure as error:
        if created:
            try:
                with psycopg.connect(database_dsn) as connection:
                    failure_projection = _projection(connection)
                packaged = packaged_birth_digests()
                failure_evidence = {
                    "schema_version": "armi.p0-s001-evidence.v1",
                    "source_revision": subprocess.run(
                        ("git", "rev-parse", "HEAD"),
                        cwd=root,
                        check=True,
                        capture_output=True,
                        text=True,
                    ).stdout.strip(),
                    "schema_target": 29,
                    "composition_digest": packaged["composition_digest"].value,
                    "result": {"status": "failed", "code": error.code},
                    "source": {
                        "kind": "life_generation_available",
                        "root_opportunity_count": failure_projection[
                            "root_opportunity_count"
                        ],
                    },
                    "projection": failure_projection,
                    "restart_projection": None,
                    "cleanup": {
                        "database": "pending",
                        "roles": "pending",
                        "runtime": "pending",
                    },
                }
                args.evidence.resolve().parent.mkdir(parents=True, exist_ok=True)
                args.evidence.resolve().write_bytes(
                    rfc8785.dumps(failure_evidence) + b"\n"
                )
                s002_status = (
                    "not_run"
                    if failure_projection["attention_opportunity_count"] == 0
                    and failure_projection["attention_episode_count"] == 0
                    else "failed"
                )
                args.s002_evidence.resolve().parent.mkdir(parents=True, exist_ok=True)
                args.s002_evidence.resolve().write_bytes(
                    rfc8785.dumps(
                        {
                            "schema_version": "armi.p0-s002-evidence.v1",
                            "source_revision": failure_evidence["source_revision"],
                            "schema_target": 29,
                            "composition_digest": packaged["composition_digest"].value,
                            "result": {
                                "status": s002_status,
                                "code": error.code,
                            },
                            "projection": None,
                            "restart_projection": None,
                            "cleanup": {
                                "database": "pending",
                                "roles": "pending",
                                "runtime": "pending",
                            },
                        }
                    )
                    + b"\n"
                )
            except OSError, psycopg.Error, subprocess.SubprocessError:
                pass
        print(
            json.dumps({"code": error.code, "status": "failed"}, separators=(",", ":"))
        )
        return 1
    finally:
        if process is not None and process.poll() is None:
            try:
                _stop_runtime(process)
            except AcceptanceFailure:
                if process.poll() is None:
                    process.kill()
                    process.communicate()
        if created:
            with psycopg.connect(provisioner, autocommit=True) as connection:
                connection.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                        sql.Identifier(database)
                    )
                )
                for role in roles:
                    connection.execute(
                        sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role))
                    )
        if work is not None and work.is_dir():
            expected_parent = (root / ".tmp").resolve()
            if work.parent != expected_parent or not work.name.startswith("p0-s001-"):
                raise RuntimeError("unsafe P0-S001 temporary root")
            shutil.rmtree(work)
        evidence_path = args.evidence.resolve()
        if evidence_path.is_file():
            document = json.loads(evidence_path.read_bytes())
            document["cleanup"] = {
                "database": "removed",
                "roles": "removed",
                "runtime": "stopped",
            }
            evidence_path.write_bytes(rfc8785.dumps(document) + b"\n")
        s002_path = args.s002_evidence.resolve()
        if s002_path.is_file():
            s002_document = json.loads(s002_path.read_bytes())
            s002_document["cleanup"] = {
                "database": "removed",
                "roles": "removed",
                "runtime": "stopped",
            }
            s002_path.write_bytes(rfc8785.dumps(s002_document) + b"\n")
    evidence_path = args.evidence.resolve()
    document = json.loads(evidence_path.read_bytes())
    document["cleanup"] = {
        "database": "removed",
        "roles": "removed",
        "runtime": "stopped",
    }
    evidence_path.write_bytes(rfc8785.dumps(document) + b"\n")
    s002_path = args.s002_evidence.resolve()
    s002_document = json.loads(s002_path.read_bytes())
    s002_document["cleanup"] = {
        "database": "removed",
        "roles": "removed",
        "runtime": "stopped",
    }
    s002_path.write_bytes(rfc8785.dumps(s002_document) + b"\n")
    print(
        json.dumps(
            {
                "status": status,
                "activity_id": document["projection"]["activity"]["activity_id"],
                "evidence_sha256": _sha256(evidence_path.read_bytes()),
                "s002_evidence_sha256": _sha256(s002_path.read_bytes()),
            },
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
