"""Run grouped source tests with bounded Python, database and Vitest pools."""

from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import sys
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import ExitStack
from pathlib import Path
from uuid import uuid4

from tools.isolated_postgresql import isolated_postgresql
from tools.pytest_groups import web_files
from tools.quality import pytest_worker_arguments


def allocation(jobs: int, database_jobs: int, lanes: set[str]) -> dict[str, int]:
    """Pools share one budget; small budgets run lanes in successive waves."""
    result = {}
    if "database" in lanes:
        result["database"] = (
            min(database_jobs, max(1, jobs // 3))
            if len(lanes) > 1
            else min(jobs, database_jobs)
        )
    if "web" in lanes:
        result["web"] = min(
            2, max(1, jobs - sum(result.values()) - ("offline" in lanes))
        )
    if "offline" in lanes:
        result["offline"] = max(1, jobs - sum(result.values()))
    return result


def clean_environment() -> dict[str, str]:
    return {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("ARMI_", "S009_", "S026_", "S033_", "PYTEST_"))
    } | {"PYTHONIOENCODING": "utf-8", "UV_OFFLINE": "1", "NPM_CONFIG_OFFLINE": "true"}


def run(
    command: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    log: Path,
    cancel: threading.Event | None = None,
) -> int:
    with log.open("w", encoding="utf-8") as output:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=environment,
            stdout=output,
            stderr=subprocess.STDOUT,
        )
        try:
            while True:
                if cancel is not None and cancel.is_set():
                    return 130
                try:
                    return process.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    continue
        finally:
            if process.poll() is None:
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
                process.wait()


def run_lane(
    name: str,
    workers: int,
    root: Path,
    output: Path,
    groups: list[str],
    cancel: threading.Event,
) -> int:
    started = time.monotonic()
    print(f"START {name}: {workers} workers", flush=True)
    log = output / f"{name}.log"
    environment = clean_environment()
    try:
        with ExitStack() as stack:
            if name == "web":
                cwd = root / "apps/armi-creator-web"
                command = [
                    str(
                        root
                        / ".armi-tools/installs/node/node-v24.18.0-win-x64/node.exe"
                    ),
                    "node_modules/vitest/vitest.mjs",
                    "run",
                    "--config",
                    "vitest.config.ts",
                    "--maxWorkers",
                    str(workers),
                    "--reporter=default",
                    "--reporter=json",
                    f"--outputFile={output / 'web.json'}",
                ]
                if groups:
                    command.extend(
                        str(path.relative_to(cwd)).replace("\\", "/")
                        for path, labels in web_files(root).items()
                        if set(groups) & labels
                    )
            else:
                cwd = root
                if name == "database":
                    databases = []
                    for _ in range(workers):
                        if cancel.is_set():
                            return 130
                        databases.append(stack.enter_context(isolated_postgresql(root)))
                    environment["ARMI_TEST_POSTGRESQL_WORKER_DSNS"] = json.dumps(
                        [database.admin_dsn for database in databases]
                    )
                    environment["S003_POSTGRESQL_CLIENT_ROOT"] = str(
                        root / ".armi-tools/installs/postgresql/18.4/pgsql"
                    )
                command = [
                    sys.executable,
                    "-B",
                    "-m",
                    "pytest",
                    "--test-lane",
                    name,
                    "-q",
                    "--tb=short",
                    "--durations=15",
                    f"--junitxml={output / (name + '.xml')}",
                    *pytest_worker_arguments(workers),
                ]
                for group in groups:
                    command.extend(("--test-group", group))
            if cancel.is_set():
                return 130
            code = run(
                command, cwd=cwd, environment=environment, log=log, cancel=cancel
            )
    except Exception as error:
        # Exception messages from database drivers can contain connection secrets.
        print(f"FAIL {name}: {type(error).__name__}", flush=True)
        return 1
    if name == "web" and (output / "web.json").exists():
        report = json.loads((output / "web.json").read_text(encoding="utf-8"))
        print(
            f"RESULT web: tests={report['numTotalTests']}, passed={report['numPassedTests']}, failed={report['numFailedTests']}, skipped={report['numPendingTests']}",
            flush=True,
        )
    elif (output / (name + ".xml")).exists():
        report = ET.parse(output / (name + ".xml")).getroot()
        suites = list(report.iter("testsuite"))
        totals = {
            key: sum(int(suite.get(key, "0")) for suite in suites)
            for key in ("tests", "failures", "errors", "skipped")
        }
        print(f"RESULT {name}: {totals}", flush=True)
        if name == "database" and totals["skipped"]:
            print("Database tests were skipped; this run is incomplete.", flush=True)
            code = 1
    print(
        f"END {name}: exit={code}, seconds={time.monotonic() - started:.1f}, log={log}",
        flush=True,
    )
    print(log.read_text(encoding="utf-8", errors="replace")[-10000:], flush=True)
    return code


def main() -> int:
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--all", action="store_true")
    selection.add_argument("--group", action="append", default=[])
    selection.add_argument("--list", action="store_true")
    parser.add_argument("--database", action="store_true")
    parser.add_argument(
        "--jobs", type=int, default=min(14, max(1, (os.cpu_count() or 1) - 2))
    )
    parser.add_argument("--database-jobs", type=int, default=4)
    args = parser.parse_args()
    if not 1 <= args.jobs <= 32 or not 1 <= args.database_jobs <= 16:
        parser.error("jobs must be 1..32; database-jobs must be 1..16")
    root = Path(__file__).resolve().parents[1]
    output = root / ".tmp/test-runs" / uuid4().hex
    output.mkdir(parents=True)
    started = time.monotonic()
    print(f"Test output: {output}", flush=True)
    inventory_path = output / "inventory.json"
    collect = [
        sys.executable,
        "-B",
        "-m",
        "pytest",
        "--collect-only",
        "-qq",
        "--test-inventory",
        str(inventory_path),
    ]
    for group in args.group:
        collect.extend(("--test-group", group))
    code = run(
        collect,
        cwd=root,
        environment=clean_environment(),
        log=output / "collection.log",
    )
    if code not in (0, 5) or not inventory_path.exists():
        print((output / "collection.log").read_text(encoding="utf-8", errors="replace"))
        return code or 1
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    if args.list:
        for group, counts in sorted(inventory["groups"].items()):
            print(f"{group}: {counts}")
        return 0
    counts = inventory["selected"]
    lanes = {name for name in ("offline", "database") if counts.get(name, 0)}
    if not (args.all or args.database):
        lanes.discard("database")
    if counts.get("web_files", 0):
        lanes.add("web")
    if not lanes:
        print("No tests selected; database groups require --database.")
        return 5
    slots = allocation(args.jobs, args.database_jobs, lanes)
    print(
        f"Collected Python={inventory['collected']}, selected={counts}, deselected={inventory['excluded']}; pools={slots}; total budget={args.jobs}",
        flush=True,
    )
    pending = sorted(lanes, key=lambda name: name != "database")
    results = {}
    running = {}
    cancel = threading.Event()
    with ThreadPoolExecutor(max_workers=len(lanes)) as executor:
        while pending or running:
            used = sum(slots[name] for name in running.values())
            for name in pending.copy():
                if used + slots[name] <= args.jobs:
                    running[
                        executor.submit(
                            run_lane,
                            name,
                            slots[name],
                            root,
                            output,
                            args.group,
                            cancel,
                        )
                    ] = name
                    pending.remove(name)
                    used += slots[name]
            try:
                completed, _ = wait(running, return_when=FIRST_COMPLETED)
            except KeyboardInterrupt:
                cancel.set()
                results.update({name: 130 for name in pending})
                pending.clear()
                print(
                    "Stopping test workers and cleaning isolated databases...",
                    flush=True,
                )
                continue
            for future in completed:
                results[running.pop(future)] = future.result()
    print(
        f"TESTS {'PASS' if not any(results.values()) else 'FAIL'}: {results}; seconds={time.monotonic() - started:.1f}; output={output}"
    )
    return int(any(results.values()))


if __name__ == "__main__":
    raise SystemExit(main())
