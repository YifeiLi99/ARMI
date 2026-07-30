"""Verify the packaged Creator shell in the pinned local Chromium."""

from __future__ import annotations

import argparse
import functools
import hashlib
import http.server
import json
import os
import shutil
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any

from playwright.sync_api import ViewportSize, sync_playwright

VIEWPORTS: tuple[ViewportSize, ...] = (
    {"width": 390, "height": 844},
    {"width": 1024, "height": 768},
    {"width": 1280, "height": 800},
    {"width": 1920, "height": 1080},
)


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    environment_id = "018f47a6-7b2d-7c35-8b18-684e38ab6ef7"
    creator_party_id = "018f47a6-7b2d-7c35-8b18-684e38ab6ef8"
    bootstrap_code = "bootstrap-v1." + ("b" * 22)
    session_token = "browser-v1." + ("a" * 43)
    event_epoch = "e" * 22
    timeline_reads = 0
    event_streams = 0

    def log_message(self, format: str, *args: object) -> None:
        del format, args

    def _json_response(self, status: int, value: dict[str, object]) -> None:
        content = json.dumps(value, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    @classmethod
    def _session_metadata(cls) -> dict[str, object]:
        return {
            "contract_version": "1.0",
            "environment_id": cls.environment_id,
            "creator_party_id": cls.creator_party_id,
            "default_scene_key": "default",
            "issued_at": "2026-07-30T10:00:00.000000Z",
            "expires_at": "2026-07-30T18:00:00.000000Z",
        }

    def do_POST(self) -> None:
        if self.path != "/v1/browser-sessions":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            request = json.loads(self.rfile.read(length))
        except ValueError, json.JSONDecodeError:
            self.send_error(400)
            return
        if request != {"bootstrap_code": self.bootstrap_code}:
            self.send_error(401)
            return
        self._json_response(
            200,
            {
                **self._session_metadata(),
                "browser_session_token": self.session_token,
            },
        )

    def do_GET(self) -> None:
        if self.path == "/v1/browser-sessions/current":
            self._json_response(200, self._session_metadata())
            return
        if self.path == "/v1/runtime/status":
            self._json_response(
                200,
                {
                    "contract_version": "1.0",
                    "environment_id": self.environment_id,
                    "runtime_state": "ready",
                    "readiness": "ready",
                    "reason_codes": [],
                    "observed_at": "2026-07-30T10:00:01.000000Z",
                },
            )
            return
        if self.path == "/v1/scenes/default/timeline?limit=50":
            type(self).timeline_reads += 1
            items: list[dict[str, object]] = []
            if type(self).timeline_reads > 1:
                items.append(
                    {
                        "timeline_item_id": ("018f47a6-7b2d-7c35-8b18-684e38ab6efa"),
                        "source_kind": "browser.event",
                        "source_ref": "018f47a6-7b2d-7c35-8b18-684e38ab6efb",
                        "status": "completed",
                        "occurred_at": "2026-07-30T10:02:00.000000Z",
                    }
                )
            self._json_response(
                200,
                {
                    "contract_version": "1.0",
                    "projection_version": "scene-timeline.v1",
                    "scene_key": "default",
                    "items": items,
                },
            )
            return
        if self.path == "/v1/scenes/default/events":
            if (
                self.headers.get("Authorization") != f"Bearer {self.session_token}"
                or self.headers.get("Accept") != "text/event-stream"
                or self.headers.get("Cookie") is not None
            ):
                self.send_error(403)
                return
            type(self).event_streams += 1
            event_id = f"sse-v1.{self.event_epoch}.1"
            data = json.dumps(
                {
                    "contract_version": "1.0",
                    "event_id": event_id,
                    "event_kind": "scene.timeline.invalidated",
                    "resource_kind": "scene_timeline",
                    "resource_ref": "default",
                    "projection_version": "scene-timeline.v1",
                    "occurred_at": "2026-07-30T10:02:00.000000Z",
                },
                separators=(",", ":"),
            )
            content = (
                "retry: 1000\n\n"
                f"id: {event_id}\n"
                "event: scene.timeline.invalidated\n"
                f"data: {data}\n\n"
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return
        super().do_GET()

    def do_DELETE(self) -> None:
        if self.path != "/v1/browser-sessions/current":
            self.send_error(404)
            return
        self.send_response(204)
        self.end_headers()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument("--tool-root", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    tool_root = (
        args.tool_root.resolve()
        if args.tool_root
        else Path(os.environ.get("ARMI_TOOL_ROOT", str(root / ".armi-tools"))).resolve()
    )
    executable = tool_root / "installs/playwright/chromium-1228/chrome-win64/chrome.exe"
    static = (
        root / "apps/armi-runtime/src/armi_runtime/interfaces/"
        "creator_web_resources/static"
    )
    if not executable.is_file():
        print("WEB-BROWSER-TOOL: pinned Chromium is missing", file=sys.stderr)
        return 2
    if not (static / "index.html").is_file():
        print("WEB-BROWSER-ASSET: packaged Creator entry is missing", file=sys.stderr)
        return 1

    results: list[dict[str, Any]] = []
    temporary_root = root / ".tmp"
    temporary_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="creator-browser-",
        dir=temporary_root,
    ) as temporary:
        served = Path(temporary)
        shutil.copytree(static, served / "ui")
        handler = functools.partial(QuietHandler, directory=str(served))
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        port = int(server.server_address[1])
        origin = f"http://127.0.0.1:{port}"
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    executable_path=str(executable),
                    headless=True,
                )
                try:
                    for viewport in VIEWPORTS:
                        QuietHandler.timeline_reads = 0
                        QuietHandler.event_streams = 0
                        page = browser.new_page(viewport=viewport)
                        requests: list[str] = []
                        page.on(
                            "request",
                            lambda request, captured=requests: captured.append(
                                request.url
                            ),
                        )
                        response = page.goto(
                            f"{origin}/ui/",
                            wait_until="networkidle",
                        )
                        if response is None or response.status != 200:
                            raise RuntimeError("WEB-BROWSER-HTTP: entry did not load")
                        heading = page.get_by_role(
                            "heading",
                            name="ARMI Creator",
                        )
                        code_input = page.get_by_label("Bootstrap code")
                        if not heading.is_visible() or not code_input.is_visible():
                            raise RuntimeError(
                                "WEB-BROWSER-VISIBLE: session entry is hidden"
                            )
                        code_input.fill(QuietHandler.bootstrap_code)
                        page.get_by_role(
                            "button",
                            name="建立浏览器会话",
                        ).click()
                        page.get_by_text("浏览器会话已建立").wait_for()
                        page.get_by_text("browser.event").wait_for()
                        if (
                            QuietHandler.timeline_reads < 2
                            or QuietHandler.event_streams < 1
                        ):
                            raise RuntimeError(
                                "WEB-BROWSER-SSE: invalidation did not refetch "
                                "the authoritative timeline"
                            )
                        page.get_by_role("button", name="刷新").click()
                        page.wait_for_load_state("networkidle")
                        if page.get_by_text("ready").count() != 2:
                            raise RuntimeError(
                                "WEB-BROWSER-STATUS: authenticated state is missing"
                            )
                        storage = page.evaluate(
                            "() => JSON.parse("
                            "sessionStorage.getItem('armi.browser-session.v1'))"
                        )
                        if storage != {
                            "token": QuietHandler.session_token,
                            "expiresAt": "2026-07-30T18:00:00.000000Z",
                            "environmentId": QuietHandler.environment_id,
                        }:
                            raise RuntimeError(
                                "SEC-WEB-STORAGE: browser session storage drifted"
                            )
                        if QuietHandler.session_token in page.content():
                            raise RuntimeError(
                                "SEC-WEB-TOKEN-DOM: session token reached the DOM"
                            )
                        page.reload(wait_until="networkidle")
                        page.get_by_text("浏览器会话已建立").wait_for()
                        page.get_by_text("browser.event").wait_for()
                        overflow = page.evaluate(
                            "() => document.documentElement.scrollWidth > "
                            "document.documentElement.clientWidth"
                        )
                        if overflow:
                            raise RuntimeError(
                                "WEB-BROWSER-OVERFLOW: horizontal overflow detected"
                            )
                        if any(not request.startswith(origin) for request in requests):
                            raise RuntimeError(
                                "SEC-WEB-REQUEST: external browser request detected"
                            )
                        page.get_by_role("button", name="注销").click()
                        code_input = page.get_by_label("Bootstrap code")
                        code_input.wait_for()
                        if (
                            page.evaluate(
                                "() => sessionStorage.getItem("
                                "'armi.browser-session.v1')"
                            )
                            is not None
                        ):
                            raise RuntimeError(
                                "SEC-WEB-LOGOUT: logout retained browser session"
                            )
                        if page.evaluate("() => localStorage.length") != 0:
                            raise RuntimeError(
                                "SEC-WEB-EVENT-CACHE: event state reached "
                                "persistent browser storage"
                            )
                        results.append(
                            {
                                "width": viewport["width"],
                                "height": viewport["height"],
                                "requests": len(requests),
                                "horizontal_overflow": False,
                                "session_flow": "pass",
                                "event_stream": "pass",
                            }
                        )
                        page.close()
                finally:
                    browser.close()
        except RuntimeError as error:
            print(str(error), file=sys.stderr)
            return 1
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    print(
        json.dumps(
            {
                "status": "pass",
                "chromium_sha256": sha256_file(executable),
                "viewports": results,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
