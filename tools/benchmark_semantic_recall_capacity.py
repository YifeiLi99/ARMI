"""Benchmark the scalable semantic-recall SQL on unique isolated data."""

# ruff: noqa: RUF001

from __future__ import annotations

import argparse
import json
import math
import os
import secrets
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

import psycopg

_IMAGE = "pgvector/pgvector:0.8.6-pg18-trixie"
_MODEL_BINDING = "armi.embedding.qwen3-0_6b-q8_0-local-1024.v1"


def _port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=False,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _nearest_rank_p95(values: list[float]) -> float:
    return sorted(values)[math.ceil(len(values) * 0.95) - 1]


def _wait_for_postgres(container: str) -> None:
    deadline = time.monotonic() + 60
    consecutive_ready = 0
    while time.monotonic() < deadline:
        ready = _run(
            [
                "docker",
                "exec",
                container,
                "pg_isready",
                "--username=bench_admin",
                "--dbname=postgres",
            ]
        )
        if ready.returncode == 0:
            consecutive_ready += 1
            if consecutive_ready == 2:
                return
            time.sleep(0.5)
            continue
        consecutive_ready = 0
        time.sleep(0.25)
    raise RuntimeError("BENCHMARK-POSTGRES-READY")


def _create_schema(connection: psycopg.Connection[Any]) -> None:
    connection.execute(
        """CREATE SCHEMA bench;
           CREATE TABLE bench.owners (
             source_ref bigint PRIMARY KEY,
             is_current boolean NOT NULL
           );
           CREATE TABLE bench.projections (
             projection_id bigint PRIMARY KEY,
             source_ref bigint NOT NULL,
             subject_id bigint NOT NULL,
             life_generation_id bigint NOT NULL,
             model_binding text NOT NULL,
             retrieval_text text NOT NULL,
             embedding armi_extensions.vector(1024) NOT NULL
           );"""
    )


def _insert_rows(
    connection: psycopg.Connection[Any], start: int, stop: int
) -> float:
    started = time.perf_counter()
    connection.execute(
        """INSERT INTO bench.owners (source_ref,is_current)
           SELECT row_id,true
           FROM generate_series(%s::bigint,%s::bigint) AS row_id""",
        (start, stop),
    )
    connection.execute(
        """INSERT INTO bench.projections (
             projection_id,source_ref,subject_id,life_generation_id,
             model_binding,retrieval_text,embedding
           )
           SELECT row_id,row_id,1,1,%s,
                  format(
                    '生活资料块 %%s；专属编号 ARMI-%%s；日期 20%%s-%%s-%%s；'
                    '设备序列 DEV-%%s；这是用于模拟长期生活资料的唯一中文段落。%%s',
                    row_id,lpad(row_id::text,8,'0'),
                    20+(row_id%%10),1+(row_id%%12),1+(row_id%%28),
                    lpad(((row_id*7919)%%100000000)::text,8,'0'),
                    repeat(' 包含偏好、人物、活动、地点和时间等自然语义。',8)
                  ),
                  vector_text::armi_extensions.vector(1024)
           FROM generate_series(%s::bigint,%s::bigint) AS row_id
           CROSS JOIN LATERAL (
             SELECT '[' || string_agg(
               ((pg_catalog.hashtextextended(
                    row_id::text || ':' || dimension::text,90210
                  ) %% 2000001)::double precision / 1000000.0)::text,
               ',' ORDER BY dimension
             ) || ']' AS vector_text
             FROM generate_series(1,1024) AS dimension
           ) AS generated""",
        (_MODEL_BINDING, start, stop),
    )
    connection.commit()
    return time.perf_counter() - started


def _build_indexes(connection: psycopg.Connection[Any]) -> float:
    connection.execute("SET maintenance_work_mem='1GB'")
    connection.execute("SET max_parallel_maintenance_workers=7")
    started = time.perf_counter()
    connection.execute(
        """CREATE INDEX projections_embedding_hnsw_idx
             ON bench.projections USING hnsw (
               (embedding::armi_extensions.halfvec(1024))
                 armi_extensions.halfvec_cosine_ops
             ) WITH (m=16,ef_construction=128);
           CREATE INDEX projections_retrieval_gist_idx
             ON bench.projections USING gist (
               retrieval_text armi_extensions.gist_trgm_ops(siglen=64)
             );"""
    )
    connection.commit()
    return time.perf_counter() - started


def _sample_ids(rows: int, count: int) -> list[int]:
    return [1 + (offset * 104729) % rows for offset in range(count)]


def _exact_top32(
    connection: psycopg.Connection[Any], vector: str
) -> tuple[int, ...]:
    rows = connection.execute(
        """SELECT projection_id FROM bench.projections
           ORDER BY embedding OPERATOR(armi_extensions.<=>)
                    %s::armi_extensions.vector(1024),projection_id
           LIMIT 32""",
        (vector,),
    ).fetchall()
    return tuple(int(row[0]) for row in rows)


def _ann_top32(
    connection: psycopg.Connection[Any], vector: str, ef_search: int
) -> tuple[int, ...]:
    connection.execute("SELECT set_config('hnsw.ef_search',%s,false)", (str(ef_search),))
    connection.execute(
        "SELECT set_config('hnsw.iterative_scan','relaxed_order',false)"
    )
    rows = connection.execute(
        """WITH nearest AS MATERIALIZED (
             SELECT projection_id,embedding FROM bench.projections
             ORDER BY embedding::armi_extensions.halfvec(1024)
                       OPERATOR(armi_extensions.<=>)
                      %s::armi_extensions.halfvec(1024)
             LIMIT 256
           )
           SELECT projection_id FROM nearest
           ORDER BY embedding OPERATOR(armi_extensions.<=>)
                    %s::armi_extensions.vector(1024),projection_id
           LIMIT 32""",
        (vector, vector),
    ).fetchall()
    return tuple(int(row[0]) for row in rows)


def _pipeline_once(
    connection: psycopg.Connection[Any], target: int, vector: str
) -> tuple[float, float, float, float]:
    started = time.perf_counter()
    dense = _ann_top32(connection, vector, 256)
    dense_ms = (time.perf_counter() - started) * 1000
    started = time.perf_counter()
    lexical = tuple(
        int(row[0])
        for row in connection.execute(
            """WITH nearest AS MATERIALIZED (
                 SELECT projection_id,source_ref,retrieval_text
                 FROM bench.projections
                 ORDER BY %s OPERATOR(armi_extensions.<<->) retrieval_text
                 LIMIT 128
               )
               SELECT projection_id FROM nearest
               ORDER BY
                 (position(lower(%s) in lower(retrieval_text))>0) DESC,
                 armi_extensions.word_similarity(%s,retrieval_text) DESC,
                 projection_id
               LIMIT 32""",
            (
                f"专属编号 ARMI-{target:08d}",
                f"ARMI-{target:08d}",
                f"专属编号 ARMI-{target:08d}",
            ),
        ).fetchall()
    )
    lexical_ms = (time.perf_counter() - started) * 1000
    candidates = tuple(dict.fromkeys((*dense, *lexical)))
    started = time.perf_counter()
    current = {
        int(row[0])
        for row in connection.execute(
            """SELECT source_ref FROM bench.owners
               WHERE source_ref=ANY(%s) AND is_current""",
            (list(candidates),),
        ).fetchall()
    }
    owner_ms = (time.perf_counter() - started) * 1000
    started = time.perf_counter()
    dense_rank = {item: rank for rank, item in enumerate(dense, 1) if item in current}
    lexical_rank = {
        item: rank for rank, item in enumerate(lexical, 1) if item in current
    }
    sorted(
        current,
        key=lambda item: (
            -(1 / (60 + dense_rank[item]) if item in dense_rank else 0)
            -(1 / (60 + lexical_rank[item]) if item in lexical_rank else 0),
            item,
        ),
    )[:6]
    rrf_ms = (time.perf_counter() - started) * 1000
    return dense_ms, lexical_ms, owner_ms, rrf_ms


def _benchmark(
    connection: psycopg.Connection[Any], rows: int, queries: int
) -> dict[str, object]:
    sample_ids = _sample_ids(rows, queries)
    vectors = {
        int(row[0]): str(row[1])
        for row in connection.execute(
            """SELECT projection_id,embedding::text FROM bench.projections
               WHERE projection_id=ANY(%s)""",
            (sample_ids,),
        ).fetchall()
    }
    ann_recall: dict[str, float] = {}
    exact = {target: _exact_top32(connection, vectors[target]) for target in sample_ids}
    for ef_search in (256, 384, 512):
        hits = 0
        total = 0
        for target in sample_ids:
            expected = set(exact[target])
            actual = set(_ann_top32(connection, vectors[target], ef_search))
            hits += len(expected & actual)
            total += len(expected)
        ann_recall[str(ef_search)] = round(hits / total, 6)
    for target in sample_ids[:5]:
        _pipeline_once(connection, target, vectors[target])
    latencies: list[float] = []
    channel_latencies: dict[str, list[float]] = {
        "dense": [],
        "lexical": [],
        "owner": [],
        "rrf": [],
    }
    for target in sample_ids:
        started = time.perf_counter()
        segments = _pipeline_once(connection, target, vectors[target])
        latencies.append((time.perf_counter() - started) * 1000)
        for name, value in zip(channel_latencies, segments, strict=True):
            channel_latencies[name].append(value)
    sizes = connection.execute(
        """SELECT pg_table_size('bench.projections'),
                  pg_indexes_size('bench.projections'),
                  pg_total_relation_size('bench.projections'),
                  pg_relation_size('bench.projections_embedding_hnsw_idx'),
                  pg_relation_size('bench.projections_retrieval_gist_idx')"""
    ).fetchone()
    assert sizes is not None
    return {
        "rows": rows,
        "queries": queries,
        "ann_recall_at_32": ann_recall,
        "database_pipeline_ms": {
            "median": round(sorted(latencies)[len(latencies) // 2], 3),
            "p95": round(_nearest_rank_p95(latencies), 3),
            "max": round(max(latencies), 3),
        },
        "channel_p95_ms": {
            name: round(_nearest_rank_p95(values), 3)
            for name, values in channel_latencies.items()
        },
        "storage_mib": {
            "table": round(int(sizes[0]) / 1024 / 1024, 2),
            "indexes": round(int(sizes[1]) / 1024 / 1024, 2),
            "total": round(int(sizes[2]) / 1024 / 1024, 2),
            "hnsw": round(int(sizes[3]) / 1024 / 1024, 2),
            "gist": round(int(sizes[4]) / 1024 / 1024, 2),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=100_000)
    parser.add_argument("--queries", type=int, default=30)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    if args.rows < 10_000 or args.queries < 10:
        raise SystemExit("rows must be >=10000 and queries must be >=10")
    root = args.root.resolve()
    init_script = root / "tools/docker/postgresql/initdb/00-vector.sql"
    if _run(["docker", "info", "--format", "{{.ServerVersion}}"]).returncode != 0:
        raise SystemExit("Docker Engine is unavailable")
    port = _port()
    password = secrets.token_urlsafe(32)
    container = f"armi-semantic-benchmark-{os.getpid()}-{secrets.token_hex(4)}"
    temporary_root = root / ".tmp"
    temporary_root.mkdir(exist_ok=True)
    started = False
    with tempfile.TemporaryDirectory(prefix="semantic-benchmark-", dir=temporary_root) as temporary:
        environment_file = Path(temporary) / "container.env"
        environment_file.write_text(
            "\n".join(
                (
                    "POSTGRES_DB=postgres",
                    "POSTGRES_USER=bench_admin",
                    f"POSTGRES_PASSWORD={password}",
                    "POSTGRES_INITDB_ARGS=--encoding=UTF8 "
                    "--locale-provider=builtin --builtin-locale=C.UTF-8",
                    "TZ=UTC",
                    "",
                )
            ),
            encoding="utf-8",
            newline="\n",
        )
        try:
            launch = _run(
                [
                    "docker",
                    "run",
                    "--detach",
                    "--name",
                    container,
                    "--env-file",
                    os.fspath(environment_file),
                    "--shm-size",
                    "2g",
                    "--publish",
                    f"127.0.0.1:{port}:5432",
                    "--mount",
                    f"type=bind,src={init_script.resolve()},"
                    "dst=/docker-entrypoint-initdb.d/00-vector.sql,readonly",
                    "--tmpfs",
                    "/var/lib/postgresql:rw",
                    _IMAGE,
                    "-c",
                    "shared_buffers=256MB",
                    "-c",
                    "max_connections=20",
                ]
            )
            if launch.returncode != 0:
                raise RuntimeError(launch.stderr.strip() or "BENCHMARK-START")
            started = True
            _wait_for_postgres(container)
            dsn = f"postgresql://bench_admin:{password}@127.0.0.1:{port}/postgres"
            with psycopg.connect(dsn) as connection:
                _create_schema(connection)
                connection.commit()
                insert_seconds = _insert_rows(connection, 1, args.rows)
                index_seconds = _build_indexes(connection)
                connection.execute("ANALYZE bench.projections")
                connection.commit()
                result = _benchmark(connection, args.rows, args.queries)
            stats = _run(
                [
                    "docker",
                    "stats",
                    "--no-stream",
                    "--format",
                    "{{.CPUPerc}}|{{.MemUsage}}",
                    container,
                ]
            )
            print(
                json.dumps(
                    {
                        **result,
                        "insert_seconds": round(insert_seconds, 3),
                        "index_build_seconds": round(index_seconds, 3),
                        "container_resources_after_benchmark": stats.stdout.strip(),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 0
        except Exception:
            if started:
                logs = _run(["docker", "logs", "--tail", "80", container])
                if logs.stdout:
                    print(logs.stdout)
                if logs.stderr:
                    print(logs.stderr)
            raise
        finally:
            if started:
                _run(["docker", "rm", "--force", container])


if __name__ == "__main__":
    raise SystemExit(main())
