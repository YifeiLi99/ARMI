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
    def log_message(self, format: str, *args: object) -> None:
        del format, args


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
                        status = page.get_by_role("status")
                        if not heading.is_visible() or not status.is_visible():
                            raise RuntimeError(
                                "WEB-BROWSER-VISIBLE: required status is hidden"
                            )
                        if "Runtime 尚未连接" not in status.inner_text():
                            raise RuntimeError(
                                "WEB-BROWSER-STATUS: honest state is missing"
                            )
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
                        results.append(
                            {
                                "width": viewport["width"],
                                "height": viewport["height"],
                                "requests": len(requests),
                                "horizontal_overflow": False,
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
