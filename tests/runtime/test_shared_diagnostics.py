from __future__ import annotations

import asyncio
import io
import json
import logging
import subprocess
import threading
import warnings
from pathlib import Path
from typing import cast

import httpx
import pytest
from armi_kernel.application import diagnostic_scope, record_diagnostic
from armi_runtime_foundation import DiagnosticLog, DiagnosticQuery, exception_evidence


def test_transport_polling_is_silent_but_failures_and_owner_results_survive(
    tmp_path: Path,
) -> None:
    sink = DiagnosticLog(data_root=tmp_path, environment_id="env", instance_id="run")
    sink.install()
    try:
        for name in ("httpx", "httpcore.connection"):
            logging.getLogger(name).info("poll succeeded")
            logging.getLogger(name).warning("transport warning")
        record_diagnostic("provider.call.completed", component="provider")
        record_diagnostic(
            "provider.call.failed", component="provider", level=logging.ERROR
        )
    finally:
        sink.close()
    page = DiagnosticQuery((tmp_path / "logs",), environment_id="env").query()
    assert len(page["items"]) == 4
    assert {item["event"] for item in page["items"]} == {
        "python.log",
        "provider.call.completed",
        "provider.call.failed",
    }


@pytest.mark.parametrize("status", [400, 401, 429, 500, 503])
def test_http_evidence_survives_logging_and_query(tmp_path: Path, status: int) -> None:
    sink = DiagnosticLog(data_root=tmp_path, environment_id="env", instance_id="run")
    sink.install()
    request = httpx.Request("POST", "https://example.invalid/api?api_key=private-key")
    response = httpx.Response(
        status,
        request=request,
        headers={"x-request-id": "provider-request"},
        json={
            "error": {"message": "busy", "code": "overload"},
            "authorization": "private-token",
            "messages": ["private-input"],
        },
    )
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as error:
        with diagnostic_scope(episode_id="episode", call_id="call"):
            record_diagnostic(
                "provider.call.failed",
                component="provider",
                level=logging.ERROR,
                error=error,
                provider="test",
            )
    sink.close()
    reader = DiagnosticQuery((tmp_path / "logs",), environment_id="env")
    page = reader.query(filters={"http_status": status, "call_id": "call"})
    assert len(page["items"]) == 1
    detail = json.loads(json.dumps(reader.read(str(page["items"][0]["log_ref"]))))
    cause = detail["record"]["exception"]["chain"][0]
    assert cause["http_status"] == status
    assert cause["provider_request_id"] == "provider-request"
    serialized = json.dumps(detail)
    assert not any(
        secret in serialized
        for secret in ("private-key", "private-token", "private-input")
    )
    assert detail["next_operations"][0]["arguments"] == {"episode_id": "episode"}


def test_snapshot_survives_append_and_rotation(tmp_path: Path) -> None:
    sink = DiagnosticLog(
        data_root=tmp_path,
        environment_id="env",
        instance_id="run",
        rotation_max_bytes=1000,
    )
    for index in range(8):
        sink.write("work.completed", details={"index": index})
    reader = DiagnosticQuery((tmp_path / "logs",), environment_id="env")
    page = reader.query(limit=2)
    ids = [item["event_id"] for item in page["items"]]
    sink.write("work.new_after_snapshot")
    while page["cursor"]:
        page = reader.query(limit=2, cursor=page["cursor"])
        ids.extend(item["event_id"] for item in page["items"])
    sink.close()
    assert len(ids) == len(set(ids)) == 8


def test_context_does_not_leak_between_operations(tmp_path: Path) -> None:
    sink = DiagnosticLog(data_root=tmp_path, environment_id="env", instance_id="run")
    with diagnostic_scope(work_id="first"):
        sink.write("work.completed")
    sink.write("process.idle")
    sink.close()
    reader = DiagnosticQuery((tmp_path / "logs",), environment_id="env")
    assert len(reader.query(filters={"work_id": "first"})["items"]) == 1


def test_provider_details_do_not_override_process_query_fields(tmp_path: Path) -> None:
    sink = DiagnosticLog(data_root=tmp_path, environment_id="env", instance_id="run")
    sink.install()
    with diagnostic_scope(attempt_id="attempt"):
        record_diagnostic(
            "provider.call.failed",
            component="provider",
            level=logging.ERROR,
            service="text-generation",
            result_code="HTTP-503",
        )
    sink.close()
    page = DiagnosticQuery((tmp_path / "logs",), environment_id="env").query(
        filters={"service": "armi-runtime", "attempt_id": "attempt"}
    )
    assert len(page["items"]) == 1
    assert page["items"][0]["result_code"] == "HTTP-503"


def test_many_segments_use_bounded_durable_cursor(tmp_path: Path) -> None:
    sink = DiagnosticLog(
        data_root=tmp_path,
        environment_id="env",
        instance_id="run",
        rotation_max_bytes=1,
    )
    for index in range(200):
        sink.write("work.completed", details={"index": index})
    sink.close()
    reader = DiagnosticQuery((tmp_path / "logs",), environment_id="env")
    first = reader.query(limit=1)
    assert first["cursor"] is not None
    assert len(first["cursor"]) < 32768
    assert list((tmp_path / "logs").glob("query-*.cursor"))
    # A new CLI/MCP process can continue the same frozen manifest.
    second = DiagnosticQuery((tmp_path / "logs",), environment_id="env").query(
        limit=1, cursor=first["cursor"]
    )
    assert second["items"][0]["event_id"] != first["items"][0]["event_id"]
    for path in (tmp_path / "logs").glob("query-*.cursor"):
        path.unlink()
    with pytest.raises(ValueError, match="CURSOR-NOT-RETAINED"):
        reader.query(cursor=first["cursor"])


def test_retention_during_query_reports_gap_and_advances(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sink = DiagnosticLog(data_root=tmp_path, environment_id="env", instance_id="run")
    sink.write("work.completed")
    sink.close()
    original = Path.open

    def removed_before_open(path: Path, *args, **kwargs):
        if path.suffix == ".jsonl":
            path.unlink(missing_ok=True)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", removed_before_open)
    page = DiagnosticQuery((tmp_path / "logs",), environment_id="env").query()
    assert page["complete"]
    assert page["items"] == []
    assert page["coverage"]["missing_segments"]
    assert not page["coverage"]["evidence_complete"]


def test_query_does_not_read_other_environment(tmp_path: Path) -> None:
    sink = DiagnosticLog(
        data_root=tmp_path, environment_id="private", instance_id="run"
    )
    sink.write("work.completed")
    sink.close()
    reader = DiagnosticQuery((tmp_path / "logs",), environment_id="other")
    assert reader.query()["items"] == []


def test_non_json_error_and_size_are_bounded(tmp_path: Path) -> None:
    response = httpx.Response(
        503,
        request=httpx.Request("POST", "https://example.invalid"),
        text="<html>service unavailable</html>" * 2000,
    )
    with pytest.raises(httpx.HTTPStatusError) as caught:
        response.raise_for_status()
    evidence = json.loads(json.dumps(exception_evidence(caught.value)))
    assert evidence["chain"][0]["error_body_truncated"]
    assert len(evidence["chain"][0]["error_body"].encode()) < 16500
    sink = DiagnosticLog(data_root=tmp_path, environment_id="env", instance_id="run")
    sink.write("event.large", details={str(index): "x" * 20000 for index in range(20)})
    sink.close()
    line = next((tmp_path / "logs").glob("*.jsonl")).read_bytes()
    assert len(line) <= 65536
    assert json.loads(line)["truncation"]["original_bytes"] > 65536


def test_all_sinks_failed_is_explicit(tmp_path: Path) -> None:
    class Broken(io.StringIO):
        def write(self, value: str) -> int:
            raise OSError("full")

    (tmp_path / "logs").write_text("not a directory")
    sink = DiagnosticLog(
        data_root=tmp_path, environment_id="env", instance_id="run", fallback=Broken()
    )
    sink.write("work.failed", level=logging.ERROR)
    assert sink.status.mode == "unavailable"
    sink.close()


def test_warnings_and_subprocess_errors_do_not_expose_command_payloads(
    tmp_path: Path,
) -> None:
    sink = DiagnosticLog(data_root=tmp_path, environment_id="env", instance_id="run")
    sink.install()
    try:
        warnings.warn("isolated resource warning", ResourceWarning, stacklevel=1)
        sink.write(
            "process.failed",
            level=logging.ERROR,
            error=subprocess.TimeoutExpired(["worker", "private-conversation"], 1),
        )
    finally:
        sink.close()
    serialized = "".join(
        path.read_text(encoding="utf-8") for path in (tmp_path / "logs").glob("*.jsonl")
    )
    assert "private-conversation" not in serialized
    assert "TimeoutExpired" in serialized


def test_summary_aggregates_more_than_a_list_page(tmp_path: Path) -> None:
    sink = DiagnosticLog(data_root=tmp_path, environment_id="env", instance_id="run")
    for _ in range(205):
        sink.write("work.failed", level=logging.ERROR, result_code="TEST-FAILURE")
    sink.close()
    reader = DiagnosticQuery((tmp_path / "logs",), environment_id="env")
    first = json.loads(json.dumps(reader.summary()))
    assert first["errors"][0]["count"] == 205
    assert first["complete"]


def test_standard_logs_thread_and_async_exceptions_are_persisted(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        sink = DiagnosticLog(
            data_root=tmp_path, environment_id="env", instance_id="run"
        )
        sink.install()
        try:
            for level in (logging.INFO, logging.WARNING, logging.ERROR):
                logging.getLogger("dependency").log(level, "technical event")

            def fail() -> None:
                raise RuntimeError("worker crashed")

            thread = threading.Thread(target=fail)
            thread.start()
            thread.join()
            asyncio.get_running_loop().call_exception_handler(
                {"message": "task crashed", "exception": RuntimeError("async failure")}
            )
        finally:
            sink.close()

    asyncio.run(exercise())
    page = DiagnosticQuery((tmp_path / "logs",), environment_id="env").query()
    assert {item["event"] for item in page["items"]} == {
        "python.log",
        "thread.unhandled_exception",
        "asyncio.unhandled_exception",
    }
    assert len(page["items"]) == 5


def test_cursor_structure_and_query_binding_are_checked(tmp_path: Path) -> None:
    sink = DiagnosticLog(data_root=tmp_path, environment_id="env", instance_id="run")
    sink.write("first")
    sink.write("second")
    sink.close()
    reader = DiagnosticQuery((tmp_path / "logs",), environment_id="env")
    cursor = reader.query(limit=1)["cursor"]
    with pytest.raises(ValueError, match="QUERY-MISMATCH"):
        reader.query(cursor=cursor, filters={"level": "error"})
    with pytest.raises(ValueError):
        reader.query(cursor="e30")


def test_primary_sink_failure_uses_emergency_directory(tmp_path: Path) -> None:
    (tmp_path / "logs").write_text("blocked")
    sink = DiagnosticLog(
        data_root=tmp_path,
        emergency_root=tmp_path / "control" / "logs",
        environment_id="env",
        instance_id="run",
    )
    sink.write("emergency.event")
    assert sink.status.mode == "emergency"
    sink.close()
    page = DiagnosticQuery(
        (tmp_path / "control" / "logs",), environment_id="env"
    ).query()
    assert page["items"][0]["event"] == "emergency.event"


def test_incremental_cursor_reads_only_appends_and_keeps_empty_cursor(
    tmp_path: Path,
) -> None:
    sink = DiagnosticLog(
        data_root=tmp_path,
        environment_id="env",
        instance_id="run",
        rotation_max_bytes=1000,
    )
    reader = DiagnosticQuery((tmp_path / "logs",), environment_id="env")
    sink.write("first")
    first = reader.follow(filters={}, cursor=None)
    empty = reader.follow(filters={}, cursor=first["cursor"])
    assert empty["cursor"] == first["cursor"]
    assert not empty["items"]
    sink.write("second")
    sink.write("third")
    following = reader.follow(filters={}, cursor=empty["cursor"])
    assert [item["event"] for item in following["items"]] == ["second", "third"]
    sink.close()


@pytest.mark.parametrize(
    "failure", [httpx.ConnectTimeout, httpx.ReadTimeout, httpx.RemoteProtocolError]
)
def test_transport_failure_type_and_correlation_are_readable(
    tmp_path: Path, failure: type[httpx.RequestError]
) -> None:
    sink = DiagnosticLog(data_root=tmp_path, environment_id="env", instance_id="run")
    with diagnostic_scope(work_id="work", call_id="call"):
        sink.write(
            "provider.call.failed",
            level=logging.ERROR,
            error=failure("isolated transport failure"),
        )
    sink.close()
    reader = DiagnosticQuery((tmp_path / "logs",), environment_id="env")
    page = reader.query(filters={"call_id": "call"})
    record = json.loads(json.dumps(reader.read(str(page["items"][0]["log_ref"]))))[
        "record"
    ]
    assert record["exception"]["chain"][0]["type"] == failure.__name__
    assert record["correlation"]["work_id"] == "work"


def test_corruption_does_not_hide_later_records(tmp_path: Path) -> None:
    sink = DiagnosticLog(data_root=tmp_path, environment_id="env", instance_id="run")
    sink.write("valid.record")
    sink.close()
    path = next((tmp_path / "logs").glob("*.jsonl"))
    valid = path.read_bytes()
    path.write_bytes(
        b'{"schema_kind":"armi.diagnostic-event"}\n'
        + b"x" * 70000
        + b"\n"
        + valid
        + b'{"partial":'
    )
    page = DiagnosticQuery((tmp_path / "logs",), environment_id="env").query()
    assert [item["event"] for item in page["items"]] == ["valid.record"]
    assert cast(int, page["coverage"]["invalid_records"]) >= 2
    assert page["coverage"]["incomplete_lines"] == 1
    assert not page["coverage"]["evidence_complete"]


def test_retention_preserves_open_writer_and_reports_cursor_gap(tmp_path: Path) -> None:
    first = DiagnosticLog(data_root=tmp_path, environment_id="env", instance_id="first")
    first.write("first.event")
    first.write("second.event")
    reader = DiagnosticQuery((tmp_path / "logs",), environment_id="env")
    cursor = reader.query(limit=1)["cursor"]
    cleaner = DiagnosticLog(
        data_root=tmp_path,
        environment_id="env",
        instance_id="second",
        total_max_bytes=1,
    )
    cleaner.write("cleaner.event")
    cleaner.close()
    assert first.path is not None and first.path.exists()
    first.close()
    cleaner = DiagnosticLog(
        data_root=tmp_path, environment_id="env", instance_id="third", total_max_bytes=1
    )
    cleaner.write("cleaner.finished")
    cleaner.close()
    page = reader.query(cursor=cursor)
    assert page["coverage"]["missing_segments"]
    assert not page["coverage"]["evidence_complete"]


def test_summary_defaults_to_latest_runtime_and_indexes_exclude_older_runs(
    tmp_path: Path,
) -> None:
    for run in ("first", "second"):
        sink = DiagnosticLog(data_root=tmp_path, environment_id="env", instance_id=run)
        sink.write("work.failed", level=logging.ERROR)
        sink.close()
    reader = DiagnosticQuery((tmp_path / "logs",), environment_id="env")
    summary = json.loads(json.dumps(reader.summary()))
    assert summary["levels"]["error"] == 1
    assert summary["coverage"]["selected_filters"] == {"run_id": "second"}
    assert (
        reader.query(filters={"run_id": "second"})["coverage"][
            "indexed_segments_skipped"
        ]
        == 1
    )
    assert (
        json.loads(json.dumps(reader.summary(period="all_retained")))["levels"]["error"]
        == 2
    )
