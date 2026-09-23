"""Bounded snapshots over bound diagnostic directories; never arbitrary paths."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict, cast
from uuid import uuid4

SCAN_BYTES = 64 * 1024 * 1024
RESPONSE_BYTES = 128 * 1024


class _Snapshot(TypedDict):
    query: str
    files: list[tuple[str, int]]
    index: int
    offset: int
    positions: dict[str, int]


class DiagnosticPage(TypedDict):
    items: list[dict[str, object]]
    cursor: str | None
    complete: bool
    bytes_examined: int
    coverage: dict[str, object]


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("DIAGNOSTICS-OBJECT-INVALID")
    return cast(dict[str, object], value)


def _objects(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise ValueError("DIAGNOSTICS-ARRAY-INVALID")
    return [_object(item) for item in cast(list[object], value)]


def _snapshot(value: object, digest: str) -> _Snapshot:
    raw = _object(value)
    if raw.get("query") != digest:
        raise ValueError("DIAGNOSTICS-CURSOR-QUERY-MISMATCH")
    files = raw.get("files")
    index, offset = raw.get("index"), raw.get("offset")
    if not isinstance(files, list) or type(index) is not int or type(offset) is not int:
        raise ValueError("DIAGNOSTICS-CURSOR-INVALID")
    segments: list[tuple[str, int]] = []
    for item in cast(list[object], files):
        if not isinstance(item, list) or len(cast(list[object], item)) != 2:
            raise ValueError("DIAGNOSTICS-CURSOR-INVALID")
        key, upper = cast(list[object], item)
        if not isinstance(key, str) or type(upper) is not int or upper < 0:
            raise ValueError("DIAGNOSTICS-CURSOR-INVALID")
        segments.append((key, upper))
    if not 0 <= index <= len(segments) or offset < 0:
        raise ValueError("DIAGNOSTICS-CURSOR-INVALID")
    if index < len(segments) and offset > segments[index][1]:
        raise ValueError("DIAGNOSTICS-CURSOR-INVALID")
    positions = _object(raw.get("positions", {}))
    if any(type(item) is not int or item < 0 for item in positions.values()):
        raise ValueError("DIAGNOSTICS-CURSOR-INVALID")
    return {
        "query": digest,
        "files": segments,
        "index": index,
        "offset": offset,
        "positions": cast(dict[str, int], positions),
    }


def _encode(value: object) -> str:
    return (
        base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode())
        .decode()
        .rstrip("=")
    )


def _decode(value: str) -> object:
    try:
        return json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))
    except (ValueError, UnicodeError) as error:
        raise ValueError("DIAGNOSTICS-CURSOR-INVALID") from error


class DiagnosticQuery:
    def __init__(
        self,
        roots: tuple[Path, ...],
        *,
        environment_id: str,
        bootstrap_roots: tuple[Path, ...] = (),
    ) -> None:
        self.roots = roots + bootstrap_roots
        self._bootstrap_indices = {
            str(index) for index in range(len(roots), len(self.roots))
        }
        self.environment_id = environment_id
        self._cursor_read_bytes = 0

    def _cursor_encode(self, value: object) -> str:
        encoded = _encode(value)
        if len(encoded) <= 16384:
            return encoded
        # A snapshot may contain thousands of short-lived process segments.
        # Keep its immutable manifest local instead of returning it to the agent.
        raw = json.dumps(value, separators=(",", ":")).encode()
        if len(raw) > SCAN_BYTES:
            raise ValueError("DIAGNOSTICS-SNAPSHOT-BUDGET-EXCEEDED")
        identity = hashlib.sha256(raw).hexdigest()
        root = self.roots[0]
        root.mkdir(parents=True, exist_ok=True)
        if root.is_symlink() or getattr(root.stat(), "st_file_attributes", 0) & 0x400:
            raise ValueError("DIAGNOSTICS-CURSOR-DIRECTORY-INVALID")
        path = root / f"query-{identity}.cursor"
        temporary = root / f"query-{uuid4().hex}.tmp"
        try:
            with temporary.open("xb") as stream:
                stream.write(raw)
                stream.flush()
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return _encode({"cursor_ref": identity})

    def _cursor_decode(self, cursor: str) -> object:
        value = _object(_decode(cursor))
        if "cursor_ref" not in value:
            return value
        identity = value["cursor_ref"]
        if (
            not isinstance(identity, str)
            or len(identity) != 64
            or any(character not in "0123456789abcdef" for character in identity)
        ):
            raise ValueError("DIAGNOSTICS-CURSOR-INVALID")
        path = self.roots[0] / f"query-{identity}.cursor"
        try:
            root = self.roots[0]
            if (
                root.is_symlink()
                or getattr(root.stat(), "st_file_attributes", 0) & 0x400
            ):
                raise ValueError("DIAGNOSTICS-CURSOR-DIRECTORY-INVALID")
            info = path.lstat()
            if (
                path.is_symlink()
                or info.st_nlink != 1
                or getattr(info, "st_file_attributes", 0) & 0x400
            ):
                raise ValueError("DIAGNOSTICS-CURSOR-INVALID")
            with path.open("rb") as stream:
                raw = stream.read(SCAN_BYTES + 1)
        except FileNotFoundError as error:
            raise ValueError(
                "DIAGNOSTICS-CURSOR-NOT-RETAINED: restart query"
            ) from error
        if len(raw) > SCAN_BYTES or hashlib.sha256(raw).hexdigest() != identity:
            raise ValueError("DIAGNOSTICS-CURSOR-INVALID")
        self._cursor_read_bytes += len(raw)
        return json.loads(raw)

    def _belongs(self, record: dict[str, object], key: str) -> bool:
        return record.get("environment_id") == self.environment_id or (
            record.get("environment_id") == "unbound"
            and key.split(":", 1)[0] in self._bootstrap_indices
        )

    def _files(self) -> dict[str, Path]:
        found: dict[str, Path] = {}
        for index, root in enumerate(self.roots):
            if (
                not root.is_dir()
                or root.is_symlink()
                or getattr(root.stat(), "st_file_attributes", 0) & 0x400
            ):
                continue
            for path in root.glob("*.jsonl"):
                info = path.lstat()
                if (
                    not path.is_file()
                    or path.is_symlink()
                    or info.st_nlink != 1
                    or getattr(info, "st_file_attributes", 0) & 0x400
                ):
                    continue
                found[f"{index}:{path.name}"] = path
        return found

    @staticmethod
    def _matches(record: dict[str, object], filters: dict[str, object]) -> bool:
        flat = {
            **_object(record.get("details", {})),
            **record,
            **_object(record.get("correlation", {})),
        }
        chain = _objects(_object(record.get("exception", {})).get("chain", []))
        if chain:
            flat.update(
                {
                    k: v
                    for item in reversed(chain)
                    for k, v in item.items()
                    if k in {"http_status", "type", "provider_request_id"}
                }
            )
        for key, expected in filters.items():
            if expected is None:
                continue
            if key == "related_ids":
                if not any(
                    flat.get(identity) in values
                    for identity, values in cast(dict[str, list[str]], expected).items()
                ):
                    return False
                continue
            if key == "start" and str(record["timestamp"]) < str(expected):
                return False
            if key == "end" and str(record["timestamp"]) > str(expected):
                return False
            if (
                key == "text"
                and str(expected).casefold()
                not in json.dumps(record, ensure_ascii=False).casefold()
            ):
                return False
            if key == "levels" and record["level"] not in cast(list[str], expected):
                return False
            if (
                key not in {"start", "end", "text", "levels"}
                and flat.get(key) != expected
            ):
                return False
        return True

    def query(
        self,
        *,
        filters: dict[str, object] | None = None,
        limit: int = 50,
        cursor: str | None = None,
        full: bool = False,
        incremental: bool = False,
        scan_budget: int = SCAN_BYTES,
    ) -> DiagnosticPage:
        if not 1 <= limit <= 200:
            raise ValueError("DIAGNOSTICS-LIMIT-INVALID")
        self._cursor_read_bytes = 0
        filters = {k: v for k, v in (filters or {}).items() if v is not None}
        for key in ("start", "end"):
            if key in filters:
                parsed = datetime.fromisoformat(str(filters[key]))
                if parsed.tzinfo is None:
                    raise ValueError("DIAGNOSTICS-TIMEZONE-REQUIRED")
                filters[key] = parsed.astimezone(UTC).isoformat()
        if (
            "start" in filters
            and "end" in filters
            and str(filters["start"]) > str(filters["end"])
        ):
            raise ValueError("DIAGNOSTICS-TIME-RANGE")
        digest = hashlib.sha256(
            json.dumps(
                {
                    "environment": self.environment_id,
                    "filters": filters,
                    "incremental": incremental,
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        files = self._files()
        if cursor is None:
            state: _Snapshot = {
                "query": digest,
                "files": [
                    (key, path.stat().st_size)
                    for key, path in sorted(
                        files.items(), key=lambda item: item[1].stat().st_mtime
                    )
                ],
                "index": 0,
                "offset": 0,
                "positions": {},
            }
        else:
            state = _snapshot(self._cursor_decode(cursor), digest)
            if incremental and state["index"] >= len(state["files"]):
                changed = [
                    (key, path.stat().st_size)
                    for key, path in files.items()
                    if path.stat().st_size > state["positions"].get(key, 0)
                ]
                if not changed:
                    return {
                        "items": [],
                        "cursor": cursor,
                        "complete": True,
                        "bytes_examined": 0,
                        "coverage": {
                            "missing_segments": [
                                key for key in state["positions"] if key not in files
                            ]
                        },
                    }
                state["files"] = changed
                state["index"] = 0
                state["offset"] = state["positions"].get(changed[0][0], 0)
        items: list[dict[str, object]] = []
        scanned = self._cursor_read_bytes
        response_bytes = 0
        gaps: list[str] = []
        damaged = 0
        incomplete_lines = 0
        indexed_segments_skipped = 0
        old_format = 0
        first_at: str | None = None
        last_at: str | None = None
        sink_modes: set[str] = set()
        while state["index"] < len(state["files"]):
            key, upper = state["files"][state["index"]]
            path = files.get(key)
            if path is None:
                gaps.append(key)
                state["positions"][key] = upper
                state["index"] += 1
                state["offset"] = (
                    state["positions"].get(state["files"][state["index"]][0], 0)
                    if state["index"] < len(state["files"])
                    else 0
                )
                continue
            # Closed segment summaries are disposable indexes. Validate their byte
            # boundary before using them to exclude irrelevant runs/time ranges.
            summary_path = path.with_suffix(".summary.json")
            if (
                not state["offset"]
                and summary_path.is_file()
                and not summary_path.is_symlink()
                and scanned < scan_budget
            ):
                try:
                    with summary_path.open("rb") as summary_stream:
                        metadata = summary_stream.read(
                            min(65536, scan_budget - scanned)
                        )
                    scanned += len(metadata)
                    summary = _object(json.loads(metadata))
                    if (
                        summary.get("bytes") == upper
                        and summary.get("environment_id") == self.environment_id
                    ):
                        excluded = (
                            (
                                filters.get("run_id") is not None
                                and filters["run_id"] != summary.get("run_id")
                            )
                            or (
                                filters.get("start") is not None
                                and summary.get("last_at") is not None
                                and str(summary["last_at"]) < str(filters["start"])
                            )
                            or (
                                filters.get("end") is not None
                                and summary.get("first_at") is not None
                                and str(summary["first_at"]) > str(filters["end"])
                            )
                        )
                        if excluded:
                            indexed_segments_skipped += 1
                            state["positions"][key] = upper
                            state["offset"] = upper
                except OSError, ValueError:
                    pass
            try:
                opened = path.open("rb")
            except OSError:
                # Retention may close and remove this segment after enumeration.
                # Reuse the missing-segment path so the snapshot still advances.
                files.pop(key, None)
                continue
            with opened as stream:
                stream.seek(state["offset"])
                while stream.tell() < upper:
                    if scanned >= scan_budget:
                        break
                    start = stream.tell()
                    line = stream.readline(
                        min(65537, upper - start, scan_budget - scanned)
                    )
                    if not line or not line.endswith(b"\n"):
                        if scanned + len(line) >= scan_budget and stream.tell() < upper:
                            scanned += len(line)
                            state["offset"] = start
                            break
                        if len(line) > 65536:
                            damaged += 1
                            scanned += len(line)
                            state["offset"] = stream.tell()
                            state["positions"][key] = stream.tell()
                            continue
                        state["offset"] = upper
                        incomplete_lines += 1
                        break
                    scanned += len(line)
                    state["offset"] = stream.tell()
                    state["positions"][key] = stream.tell()
                    try:
                        record = _object(json.loads(line))
                        if record.get("schema_kind") != "armi.diagnostic-event":
                            old_format += 1
                            continue
                        if not all(
                            isinstance(record.get(field), str)
                            for field in (
                                "event_id",
                                "timestamp",
                                "event",
                                "level",
                                "service",
                            )
                        ):
                            raise ValueError("DIAGNOSTICS-RECORD-INVALID")
                        if not self._belongs(record, key):
                            continue
                        timestamp = str(record["timestamp"])
                        first_at = min(first_at, timestamp) if first_at else timestamp
                        last_at = max(last_at, timestamp) if last_at else timestamp
                        sink_modes.add(str(record.get("sink_mode", "not_reported")))
                        if not self._matches(record, filters):
                            continue
                    except (
                        ValueError,
                        UnicodeError,
                        AttributeError,
                        KeyError,
                        TypeError,
                    ):
                        damaged += 1
                        continue
                    reference = _encode(
                        {"file": key, "offset": start, "id": record["event_id"]}
                    )
                    if full:
                        item = {"log_ref": reference, **record}
                    else:
                        item = {
                            k: record.get(k)
                            for k in (
                                "event_id",
                                "timestamp",
                                "level",
                                "event",
                                "service",
                                "component",
                                "run_id",
                                "result_code",
                                "correlation",
                            )
                        }
                        item.update(
                            log_ref=reference,
                            message=str(record.get("message", ""))[:240],
                        )
                        details = _object(record.get("details", {}))
                        item.update(
                            {
                                field: record.get(field, details.get(field))
                                for field in (
                                    "outcome",
                                    "phase",
                                    "duration_ms",
                                    "result_code",
                                )
                            }
                        )
                    size = len(json.dumps(item, ensure_ascii=False).encode())
                    if response_bytes + size > RESPONSE_BYTES - 16384 - 4096:
                        state["offset"] = start
                        state["positions"][key] = start
                        break
                    items.append(item)
                    response_bytes += size
                    if len(items) >= limit or scanned >= scan_budget:
                        break
                done = state["offset"] >= upper
            if done:
                state["index"] += 1
                state["offset"] = (
                    state["positions"].get(state["files"][state["index"]][0], 0)
                    if state["index"] < len(state["files"])
                    else 0
                )
            if (
                len(items) >= limit
                or scanned >= scan_budget
                or response_bytes >= RESPONSE_BYTES - 65536
            ):
                break
        complete = state["index"] >= len(state["files"])
        return {
            "items": items,
            "cursor": None
            if complete and not incremental
            else self._cursor_encode(state),
            "complete": complete,
            "bytes_examined": scanned,
            "coverage": {
                "missing_segments": gaps,
                "invalid_records": damaged,
                "incomplete_lines": incomplete_lines,
                "indexed_segments_skipped": indexed_segments_skipped,
                "old_format_records": old_format,
                "historical_details_reconstructed": False,
                "examined_first_at": first_at,
                "examined_last_at": last_at,
                "sink_modes": sorted(sink_modes),
                "evidence_complete": complete
                and not (gaps or damaged or incomplete_lines or old_format),
            },
        }

    def read(self, log_ref: str) -> dict[str, object]:
        ref = _object(_decode(log_ref))
        offset, key = ref.get("offset"), ref.get("file")
        if type(offset) is not int or offset < 0 or not isinstance(key, str):
            raise ValueError("DIAGNOSTICS-REFERENCE-INVALID")
        path = self._files().get(key)
        if path is None:
            return {"status": "unavailable", "reason": "segment_not_retained"}
        with path.open("rb") as stream:
            stream.seek(offset)
            line = stream.readline(65537)
        record = _object(json.loads(line))
        if not self._belongs(record, key) or record.get("event_id") != ref.get("id"):
            raise ValueError("DIAGNOSTICS-REFERENCE-MISMATCH")
        links: list[dict[str, object]] = []
        ids = {
            **_object(record.get("details", {})),
            **_object(record.get("correlation", {})),
        }
        for identity in (
            "episode_id",
            "operation_id",
            "effect_id",
            "work_id",
            "opportunity_id",
            "trace_id",
        ):
            if ids.get(identity):
                links.append(
                    {"tool": "admin_trace_flow", "arguments": {identity: ids[identity]}}
                )
        if ids.get("call_id"):
            links.append(
                {"tool": "admin_usage_read", "arguments": {"call_id": ids["call_id"]}}
            )
        neighbors: list[dict[str, object]] = []
        with path.open("rb") as stream:
            lower = max(0, offset - 32768)
            stream.seek(lower)
            if lower:
                stream.readline(32768)
            budget = 65536
            while budget > 0:
                position = stream.tell()
                line = stream.readline(min(65537, budget))
                budget -= len(line)
                if not line or not line.endswith(b"\n"):
                    break
                try:
                    item = _object(json.loads(line))
                    if position != offset and self._belongs(item, key):
                        neighbors.append(
                            {
                                "timestamp": item.get("timestamp"),
                                "event": item.get("event"),
                                "level": item.get("level"),
                                "log_ref": _encode(
                                    {
                                        "file": key,
                                        "offset": position,
                                        "id": item.get("event_id"),
                                    }
                                ),
                            }
                        )
                        if position < offset:
                            neighbors = neighbors[-5:]
                        elif len(neighbors) >= 10:
                            break
                except ValueError:
                    continue
        return {
            "status": "available",
            "record": record,
            "next_operations": links,
            "context": neighbors,
            "context_scope": "same_segment",
        }

    def summary(
        self,
        *,
        filters: dict[str, object] | None = None,
        cursor: str | None = None,
        period: str = "latest_runtime",
    ) -> dict[str, object]:
        requested = filters or {}
        selection = dict(requested)
        boundary_missing = False
        metadata_bytes = 0
        storage: list[dict[str, object]] = []
        for index, root in enumerate(self.roots):
            state_path = root / "retention.status.json"
            health: dict[str, object] = {
                "directory": index,
                "exists": root.is_dir(),
                "retention_status": "unavailable",
            }
            if (
                state_path.is_file()
                and not state_path.is_symlink()
                and not root.is_symlink()
            ):
                try:
                    with state_path.open("rb") as stream:
                        raw = stream.read(8192)
                    metadata_bytes += len(raw)
                    health["retention_status"] = _object(json.loads(raw))
                except OSError, ValueError:
                    health["retention_status"] = "unreadable"
            storage.append(health)
        if cursor is not None:
            self._cursor_read_bytes = 0
            continuation = _object(self._cursor_decode(cursor))
            metadata_bytes += self._cursor_read_bytes
            if (
                continuation.get("requested") != requested
                or continuation.get("period") != period
            ):
                raise ValueError("DIAGNOSTICS-CURSOR-QUERY-MISMATCH")
            selection = _object(continuation.get("selection"))
            boundary_missing = bool(continuation.get("boundary_missing"))
            cursor = cast(str, continuation.get("cursor"))
        elif period == "since_update" and "start" not in selection:
            update_page = self.query(
                filters={"event": "update.deployed"},
                full=True,
                limit=200,
                scan_budget=SCAN_BYTES - metadata_bytes,
            )
            metadata_bytes += update_page["bytes_examined"]
            deployed = [
                item
                for item in update_page["items"]
                if _object(item.get("details", {})).get("phase") == "deployed"
            ]
            if deployed and update_page["complete"]:
                selection["start"] = max(str(item["timestamp"]) for item in deployed)
            else:
                boundary_missing = True
        elif period == "latest_runtime" and not any(
            key in selection for key in ("start", "end", "run_id")
        ):
            boundary_missing = True
            for key, path in sorted(
                self._files().items(),
                key=lambda item: item[1].stat().st_mtime,
                reverse=True,
            ):
                if not path.name.startswith(("runtime-", "startup-")):
                    continue
                with path.open("rb") as stream:
                    line = stream.readline(65536 - metadata_bytes)
                metadata_bytes += len(line)
                try:
                    record = _object(json.loads(line))
                    if self._belongs(record, key) and record.get("service") in {
                        "armi-runtime",
                        "armi-startup",
                    }:
                        selection["run_id"] = record["run_id"]
                        boundary_missing = False
                        break
                except ValueError, KeyError:
                    pass
                if metadata_bytes >= 65536:
                    break
        levels: Counter[str] = Counter()
        components: Counter[str] = Counter()
        groups: dict[str, dict[str, object]] = {}
        scanned = metadata_bytes
        damaged = old_format = 0
        incomplete_lines = 0
        first_at: str | None = None
        last_at: str | None = None
        sink_modes: set[str] = set()
        missing: set[str] = set()
        while True:
            page = self.query(
                filters=selection,
                limit=50,
                cursor=cursor,
                full=True,
                scan_budget=SCAN_BYTES - scanned,
            )
            scanned += page["bytes_examined"]
            damaged += cast(int, page["coverage"].get("invalid_records", 0))
            old_format += cast(int, page["coverage"].get("old_format_records", 0))
            incomplete_lines += cast(int, page["coverage"].get("incomplete_lines", 0))
            start_at, end_at = (
                page["coverage"].get("examined_first_at"),
                page["coverage"].get("examined_last_at"),
            )
            if start_at:
                first_at = min(first_at, str(start_at)) if first_at else str(start_at)
            if end_at:
                last_at = max(last_at, str(end_at)) if last_at else str(end_at)
            sink_modes.update(cast(list[str], page["coverage"].get("sink_modes", [])))
            missing.update(
                cast(list[str], page["coverage"].get("missing_segments", []))
            )
            for item in page["items"]:
                levels[str(item["level"])] += 1
                components[str(item.get("component", item["service"]))] += 1
                if item["level"] not in {"warning", "error", "critical"}:
                    continue
                chain = _objects(_object(item.get("exception", {})).get("chain", []))
                cause = chain[0] if chain else {}
                details = _object(item.get("details", {}))
                code = (
                    item.get("result_code")
                    or details.get("result_code")
                    or details.get("error_code")
                )
                key = json.dumps(
                    [
                        item["service"],
                        item["event"],
                        code,
                        cause.get("type"),
                        cause.get("http_status"),
                    ]
                )
                group = groups.setdefault(
                    key,
                    {
                        "event": item["event"],
                        "service": item["service"],
                        "error_code": code,
                        "exception_type": cause.get("type"),
                        "http_status": cause.get("http_status"),
                        "count": 0,
                        "first_at": item["timestamp"],
                        "last_at": item["timestamp"],
                        "representative_log_ref": item["log_ref"],
                    },
                )
                group["count"] = cast(int, group["count"]) + 1
                group["first_at"] = min(str(group["first_at"]), str(item["timestamp"]))
                group["last_at"] = max(str(group["last_at"]), str(item["timestamp"]))
            cursor = page["cursor"]
            if page["complete"] or scanned >= SCAN_BYTES or len(groups) >= 80:
                break
        return {
            "cursor": None
            if cursor is None
            else self._cursor_encode(
                {
                    "requested": requested,
                    "selection": selection,
                    "cursor": cursor,
                    "period": period,
                    "boundary_missing": boundary_missing,
                }
            ),
            "complete": page["complete"],
            "coverage": {
                "missing_segments": sorted(missing),
                "invalid_records": damaged,
                "old_format_records": old_format,
                "historical_details_reconstructed": False,
                "selected_filters": selection,
                "runtime_boundary_unavailable": boundary_missing,
                "requested_period": period,
                "storage": storage,
                "examined_first_at": first_at,
                "examined_last_at": last_at,
                "sink_modes": sorted(sink_modes),
                "incomplete_lines": incomplete_lines,
                "evidence_complete": page["complete"]
                and not (
                    missing
                    or damaged
                    or incomplete_lines
                    or old_format
                    or boundary_missing
                ),
            },
            "bytes_examined": scanned,
            "levels": dict(levels),
            "components": dict(components),
            "errors": list(groups.values()),
            "statistics_scope": "this_page",
            "observed_at": datetime.now(UTC).isoformat(),
        }

    def follow(
        self,
        *,
        filters: dict[str, object],
        cursor: str | None,
        wait_seconds: int = 0,
        limit: int = 50,
    ) -> DiagnosticPage:
        if not 0 <= wait_seconds <= 30:
            raise ValueError("DIAGNOSTICS-WAIT-INVALID")
        deadline = time.monotonic() + wait_seconds
        while True:
            page = self.query(
                filters=filters, cursor=cursor, incremental=True, limit=limit
            )
            if page["items"] or not page["complete"] or time.monotonic() >= deadline:
                return page
            cursor = page["cursor"]
            time.sleep(min(0.25, max(0, deadline - time.monotonic())))
