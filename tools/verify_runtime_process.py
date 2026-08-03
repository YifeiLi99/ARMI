"""Start the real S008 console entry point and verify its local HTTP boundary."""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

ENVIRONMENT_ID = "01980f7d-7b8f-7e2a-8a11-2ab8e1234567"


class ProcessVerificationError(RuntimeError):
    pass


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _request(
    opener: urllib.request.OpenerDirector,
    url: str,
    *,
    authorization: str | None = None,
) -> tuple[int, bytes, dict[str, str]]:
    headers = {"Authorization": authorization} if authorization is not None else {}
    request = urllib.request.Request(url, headers=headers)
    try:
        with opener.open(request, timeout=1) as response:
            return (
                response.status,
                response.read(),
                {name.lower(): value for name, value in response.headers.items()},
            )
    except urllib.error.HTTPError as error:
        return (
            error.code,
            error.read(),
            {name.lower(): value for name, value in error.headers.items()},
        )


def _wait_for_live(
    opener: urllib.request.OpenerDirector,
    origin: str,
    process: subprocess.Popen[str],
) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise ProcessVerificationError(
                "LIFE-PROCESS-EXIT: Runtime exited before liveness"
            )
        try:
            status, body, _headers = _request(opener, f"{origin}/health/live")
            if status == 200 and json.loads(body) == {"status": "alive"}:
                return
        except OSError, json.JSONDecodeError:
            pass
        time.sleep(0.05)
    raise ProcessVerificationError("LIFE-PROCESS-TIMEOUT: liveness was not reached")


def _write_environment(root: Path, port: int) -> None:
    data = root / "data"
    secrets = root / "secrets"
    data.mkdir()
    secrets.mkdir()
    (root / "environment.toml").write_text(
        "\n".join(
            (
                "[environment]",
                f'environment_id = "{ENVIRONMENT_ID}"',
                f'data_root = "{data.resolve().as_posix()}"',
                "",
                "[creator]",
                f"port = {port}",
                "",
            )
        ),
        encoding="utf-8",
        newline="\n",
    )


def _verify_logs(data_root: Path) -> tuple[str, ...]:
    logs = list((data_root / "logs").glob("runtime-*.jsonl"))
    if len(logs) != 1:
        raise ProcessVerificationError(
            "LIFE-LOG-SET: exactly one lifecycle log is required"
        )
    events: list[str] = []
    for line in logs[0].read_text(encoding="utf-8").splitlines():
        parsed = cast(object, json.loads(line))
        if not isinstance(parsed, dict):
            raise ProcessVerificationError("LIFE-LOG-FORMAT: log line is not an object")
        event = cast(dict[str, Any], parsed).get("event")
        if isinstance(event, str):
            events.append(event)
    expected = (
        "runtime.lifecycle.starting",
        "runtime.lifecycle.blocked",
        "runtime.lifecycle.draining",
        "runtime.lifecycle.stopped",
    )
    if tuple(events) != expected:
        raise ProcessVerificationError(
            "LIFE-LOG-SEQUENCE: lifecycle log sequence is invalid"
        )
    return tuple(events)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()
    entry_point = root / ".venv/Scripts/armi.exe"
    if not entry_point.is_file():
        print(
            "LIFE-PROCESS-TOOL: installed armi entry point is missing", file=sys.stderr
        )
        return 2
    temporary_root = root / ".tmp"
    temporary_root.mkdir(exist_ok=True)
    process: subprocess.Popen[str] | None = None
    try:
        with tempfile.TemporaryDirectory(
            prefix="runtime-process-",
            dir=temporary_root,
            ignore_cleanup_errors=True,
        ) as temporary:
            environment_root = Path(temporary)
            port = _free_port()
            _write_environment(environment_root, port)
            environment = {
                key: value
                for key, value in os.environ.items()
                if not key.startswith("ARMI_")
            }
            process = subprocess.Popen(
                (
                    str(entry_point),
                    "runtime",
                    "start",
                    "--environment-root",
                    str(environment_root),
                ),
                cwd=root,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            origin = f"http://127.0.0.1:{port}"
            _wait_for_live(opener, origin, process)
            ready_status, ready_body, security_headers = _request(
                opener, f"{origin}/health/ready"
            )
            missing_status, missing_body, _ = _request(
                opener, f"{origin}/v1/runtime/status"
            )
            bearer_status, bearer_body, _ = _request(
                opener,
                f"{origin}/v1/runtime/status",
                authorization="Bearer local-verification",
            )
            ui_status, ui_body, _ = _request(opener, f"{origin}/ui/")
            if (
                ready_status != 503
                or json.loads(ready_body) != {"status": "not_ready"}
                or missing_status != 503
                or json.loads(missing_body).get("status") != "unavailable"
                or bearer_status != 503
                or json.loads(bearer_body).get("status") != "unavailable"
                or ui_status != 200
                or b"ARMI Creator" not in ui_body
                or security_headers.get("x-frame-options") != "DENY"
            ):
                raise ProcessVerificationError(
                    "LIFE-HTTP-CONTRACT: Runtime HTTP responses violate S008 "
                    f"(ready={ready_status}, missing={missing_status}, "
                    f"bearer={bearer_status}, ui={ui_status}, "
                    f"frame={security_headers.get('x-frame-options')!r})"
                )
            process.send_signal(signal.CTRL_BREAK_EVENT)
            stdout, stderr = process.communicate(timeout=10)
            if process.returncode != 0:
                raise ProcessVerificationError(
                    f"LIFE-PROCESS-EXIT: graceful exit was {process.returncode}; "
                    f"stderr={stderr.strip()!r}"
                )
            if stdout:
                raise ProcessVerificationError(
                    "LIFE-STDOUT: runtime start must keep stdout empty"
                )
            events = _verify_logs(environment_root / "data")
            print(
                json.dumps(
                    {
                        "status": "pass",
                        "exit_code": process.returncode,
                        "liveness": 200,
                        "readiness": 503,
                        "creator_session_unavailable_status": 503,
                        "unverified_bearer_status": 503,
                        "ui": 200,
                        "lifecycle_events": events,
                        "stderr_lines": len(stderr.splitlines()),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
            time.sleep(0.25)
        return 0
    except (
        OSError,
        json.JSONDecodeError,
        ProcessVerificationError,
        subprocess.TimeoutExpired,
    ) as error:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
