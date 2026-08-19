"""Verify the packaged Creator shell in the pinned local Chromium."""

from __future__ import annotations

import argparse
import functools
import http.server
import json
import os
import re
import shutil
import sys
import tempfile
import threading
from collections import Counter
from pathlib import Path
from typing import Any

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
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
    session_token = "browser-v1." + ("a" * 43)
    event_epoch = "e" * 22
    timeline_reads = 0
    event_streams = 0
    input_accepted = False
    opportunity_id = "018f47a6-7b2d-7c35-8b18-684e38ab6ef9"
    capability_request_id = "018f47a6-7b2d-7c35-8b18-684e38ab6efa"
    codex_request_id = "018f47a6-7b2d-7c35-8b18-684e38ab6efb"
    grant_id = "018f47a6-7b2d-7c35-8b18-684e38ab6efc"
    effect_id = "018f47a6-7b2d-7c35-8b18-684e38ab6efd"
    capability_status = "pending"
    capability_version = 1
    effect_reads = 0

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
        if self.path == (
            f"/v1/capability-requests/{self.capability_request_id}/decision"
        ):
            length = int(self.headers.get("Content-Length", "0"))
            try:
                request = json.loads(self.rfile.read(length))
            except json.JSONDecodeError:
                self.send_error(400)
                return
            if (
                request.get("contract_version") != "1.0"
                or request.get("decision") != "limit"
                or request.get("expected_request_version") != 1
                or request.get("max_uses") != 2
                or re.fullmatch(
                    r"[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-"
                    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}",
                    str(request.get("decision_id", "")),
                )
                is None
            ):
                self.send_error(400)
                return
            type(self).capability_status = "limited"
            type(self).capability_version = 2
            self._json_response(
                200,
                {
                    "contract_version": "1.0",
                    "status": "applied",
                    "trace_id": "c" * 32,
                    "occurred_at": "2026-07-30T10:01:00.000000Z",
                    "message": "decision applied",
                    "result_ref": self.capability_request_id,
                    "state_version": 2,
                },
            )
            return
        if self.path == "/v1/scenes/default/messages":
            if (
                self.headers.get("Authorization") != f"Bearer {self.session_token}"
                or re.fullmatch(
                    r"creator-input-v1\.[A-Za-z0-9_-]{22}",
                    self.headers.get("Idempotency-Key", ""),
                )
                is None
            ):
                self.send_error(403)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                request = json.loads(self.rfile.read(length))
            except ValueError, json.JSONDecodeError:
                self.send_error(400)
                return
            if request != {
                "contract_version": "1.0",
                "message": "精确保留的 Creator 输入",
            }:
                self.send_error(400)
                return
            type(self).input_accepted = True
            self._json_response(202, self._accepted_operation())
            return
        if self.path != "/v1/browser-sessions":
            self.send_error(404)
            return
        self._json_response(
            200,
            {
                **self._session_metadata(),
                "browser_session_token": self.session_token,
            },
        )

    @classmethod
    def _accepted_operation(cls) -> dict[str, object]:
        return {
            "contract_version": "1.0",
            "status": "accepted",
            "trace_id": "a" * 32,
            "occurred_at": "2026-07-30T10:03:00.000000Z",
            "message": "The Creator input is durably accepted.",
            "result_ref": cls.opportunity_id,
            "custodian": "runtime",
            "details": {
                "interaction_id": "018f47a6-7b2d-7c35-8b18-684e38ab6efa",
                "evidence_id": "018f47a6-7b2d-7c35-8b18-684e38ab6efb",
                "opportunity_id": cls.opportunity_id,
                "operation_url": f"/v1/operations/{cls.opportunity_id}",
            },
        }

    @classmethod
    def _operation_projection(cls) -> dict[str, object]:
        return {
            "contract_version": "1.0",
            "status": "completed",
            "trace_id": "d" * 32,
            "occurred_at": "2026-07-30T10:03:02.000000Z",
            "message": "Creator response verified.",
            "result_ref": cls.effect_id,
            "details": {
                "projection_version": "creator-operation.v2",
                "operation_ref": cls.opportunity_id,
                "operation_kind": "creator_response",
                "stage": "completed",
                "outcome": "completed",
                "effect_ref": cls.effect_id,
            },
        }

    @classmethod
    def _capability_items(cls) -> list[dict[str, object]]:
        reply: dict[str, object] = {
            "capability_request_id": cls.capability_request_id,
            "capability_kind": "creator.scene.reply",
            "operation": "send",
            "subject_id": cls.environment_id,
            "scene_id": cls.creator_party_id,
            "audience_scope": "creator",
            "data_scope": "creator_visible_response",
            "purpose": "respond_to_creator",
            "valid_for_seconds": 600,
            "max_uses": 4,
            "max_payload_bytes": 4096,
            "status": cls.capability_status,
            "capability_availability": "available",
            "resolution_reason_code": None,
            "request_version": cls.capability_version,
            "created_at": "2026-07-30T10:00:00.000000Z",
            "status_changed_at": "2026-07-30T10:00:01.000000Z",
        }
        if cls.capability_status == "limited":
            reply["effective_grant"] = {
                "scope_kind": "creator_scene_reply",
                "grant_ref": cls.grant_id,
                "status": "active",
                "valid_from": "2026-07-30T10:01:00.000000Z",
                "valid_until": "2026-07-30T10:06:00.000000Z",
                "max_uses": 2,
                "consumed_uses": 0,
                "remaining_uses": 2,
                "max_payload_bytes": 4096,
            }
        return [
            reply,
            {
                "capability_request_id": cls.codex_request_id,
                "capability_kind": "codex.delegated-work",
                "operation": "execute",
                "subject_id": cls.environment_id,
                "scene_id": cls.creator_party_id,
                "purpose": "delegate_codex_work",
                "workspace_scope": "isolated_ephemeral",
                "artifact_scope": "explicit_only",
                "network_access": False,
                "valid_for_seconds": 600,
                "max_uses": 1,
                "status": "pending",
                "capability_availability": "unavailable",
                "resolution_reason_code": "CODEX-UNAVAILABLE",
                "request_version": 1,
                "created_at": "2026-07-30T09:59:00.000000Z",
                "status_changed_at": "2026-07-30T10:00:01.000000Z",
            },
        ]

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
        if self.path == "/v1/subject/summary":
            self._json_response(
                200,
                {
                    "contract_version": "1.0",
                    "projection_version": "subject-summary.v1",
                    "subject_version": 1,
                    "components": [
                        {
                            "kind": "self",
                            "version": 1,
                            "schema_version": "armi.self.v1",
                            "content_visibility": "private",
                        },
                        {
                            "kind": "mind",
                            "version": 1,
                            "schema_version": "armi.mind.v2",
                            "content_visibility": "private",
                        },
                        {
                            "kind": "life_mode",
                            "version": 1,
                            "schema_version": "armi.life-mode.v1",
                            "content_visibility": "private",
                        },
                    ],
                    "latest_commit_ref": self.opportunity_id,
                    "observed_at": "2026-07-30T10:00:01.000000Z",
                },
            )
            return
        if self.path == "/v1/capability-requests?limit=50":
            self._json_response(
                200,
                {
                    "contract_version": "1.0",
                    "projection_version": "capability-request.v4",
                    "items": self._capability_items(),
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
            if type(self).input_accepted:
                items.append(
                    {
                        "timeline_item_id": "018f47a6-7b2d-7c35-8b18-684e38ab6efc",
                        "source_kind": "creator_input",
                        "source_ref": "018f47a6-7b2d-7c35-8b18-684e38ab6efa",
                        "status": "accepted",
                        "occurred_at": "2026-07-30T10:03:00.000000Z",
                        "operation_ref": self.opportunity_id,
                    }
                )
            self._json_response(
                200,
                {
                    "contract_version": "1.0",
                    "projection_version": "scene-timeline.v5",
                    "scene_key": "default",
                    "items": items,
                },
            )
            return
        if self.path == f"/v1/operations/{self.opportunity_id}":
            self._json_response(200, self._operation_projection())
            return
        if self.path == f"/v1/effects/{self.effect_id}":
            type(self).effect_reads += 1
            self._json_response(
                200,
                {
                    "contract_version": "1.0",
                    "projection_version": "creator-effect.v3",
                    "effect_id": self.effect_id,
                    "action_intent_ref": self.opportunity_id,
                    "action_intent_revision_ref": "018f47a6-7b2d-7c35-8b18-684e38ab6efe",
                    "capability_kind": "creator.scene.reply",
                    "effect_kind": "creator_response",
                    "status": "completed",
                    "verification_status": "verified",
                    "attempt_count": 1,
                    "last_observation_kind": "receipt",
                    "last_observation_reliability": "reliable",
                    "registered_at": "2026-07-30T10:03:00.000000Z",
                    "settled_at": "2026-07-30T10:03:02.000000Z",
                    "response_text": "<img src=https://outside.invalid/x> 已核验回应",
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
                    "projection_version": "scene-timeline.v5",
                    "occurred_at": "2026-07-30T10:02:00.000000Z",
                },
                separators=(",", ":"),
            )
            content = (
                f"id: {event_id}\nevent: scene.timeline.invalidated\ndata: {data}\n\n"
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
    static = root / "apps/armi-runtime/build/creator-web-resources/static"
    if not executable.is_file():
        print("WEB-BROWSER-TOOL: pinned Chromium is missing", file=sys.stderr)
        return 2
    if not (static / "index.html").is_file():
        print("WEB-BROWSER-ASSET: built Creator entry is missing", file=sys.stderr)
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

        class QuietServer(http.server.ThreadingHTTPServer):
            def handle_error(self, request: object, client_address: object) -> None:
                del request, client_address

        server = QuietServer(("127.0.0.1", 0), handler)
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
                        QuietHandler.input_accepted = False
                        QuietHandler.capability_status = "pending"
                        QuietHandler.capability_version = 1
                        QuietHandler.effect_reads = 0
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
                            wait_until="domcontentloaded",
                        )
                        if response is None or response.status != 200:
                            raise RuntimeError("WEB-BROWSER-HTTP: entry did not load")
                        authenticated = page.locator(".authenticated-view")
                        authenticated.wait_for()
                        if not authenticated.is_visible():
                            raise RuntimeError(
                                "WEB-BROWSER-VISIBLE: Creator workspace is hidden"
                            )
                        page.get_by_text("本机连接正常").wait_for(state="attached")
                        page.get_by_text("browser.event").wait_for()
                        mobile_menu = page.get_by_role(
                            "button", name="打开导航", exact=True
                        )
                        if mobile_menu.is_visible():
                            mobile_menu.click()
                            page.wait_for_function(
                                "() => document.querySelector('.workspace-sidebar')"
                                ".getBoundingClientRect().left >= 0"
                            )
                        capability_navigation = page.get_by_role(
                            "button", name="能力授权", exact=True
                        )
                        if not capability_navigation.evaluate(
                            "element => { const rect = element.getBoundingClientRect(); "
                            "return rect.top >= 0 && rect.left >= 0 && "
                            "rect.bottom <= innerHeight && rect.right <= innerWidth; }"
                        ):
                            navigation_layout = page.locator(
                                ".primary-navigation"
                            ).evaluate(
                                "element => ({clientHeight: element.clientHeight, "
                                "scrollHeight: element.scrollHeight, "
                                "scrollTop: element.scrollTop, "
                                "rect: element.getBoundingClientRect().toJSON()})"
                            )
                            raise RuntimeError(
                                "WEB-BROWSER-NAVIGATION: capability navigation is "
                                f"unreachable; layout={navigation_layout}"
                            )
                        if viewport != VIEWPORTS[0]:
                            overflow = page.evaluate(
                                "() => document.documentElement.scrollWidth > "
                                "document.documentElement.clientWidth"
                            )
                            if overflow:
                                raise RuntimeError(
                                    "WEB-BROWSER-OVERFLOW: horizontal overflow detected"
                                )
                            cdp = page.context.new_cdp_session(page)
                            cdp.send(
                                "Emulation.setPageScaleFactor",
                                {"pageScaleFactor": 2},
                            )
                            zoom_overflow = page.evaluate(
                                "() => document.documentElement.scrollWidth > "
                                "document.documentElement.clientWidth"
                            )
                            cdp.send(
                                "Emulation.setPageScaleFactor",
                                {"pageScaleFactor": 1},
                            )
                            cdp.detach()
                            if zoom_overflow:
                                raise RuntimeError(
                                    "WEB-BROWSER-ZOOM: 200 percent zoom overflow detected"
                                )
                            if any(
                                not request.startswith(origin) for request in requests
                            ):
                                raise RuntimeError(
                                    "SEC-WEB-REQUEST: external browser request detected"
                                )
                            results.append(
                                {
                                    "width": viewport["width"],
                                    "height": viewport["height"],
                                    "requests": len(requests),
                                    "horizontal_overflow": False,
                                    "navigation_reachability": "pass",
                                    "zoom_200_percent": "pass",
                                }
                            )
                            page.close()
                            continue
                        try:
                            capability_navigation.click(timeout=2_000)
                        except PlaywrightTimeoutError as error:
                            navigation_layout = page.evaluate(
                                "() => { const nav = document.querySelector("
                                "'.primary-navigation'); const item = Array.from("
                                "document.querySelectorAll('.navigation-item')).find("
                                "element => element.textContent.includes('能力授权')); "
                                "const sidebar = document.querySelector("
                                "'.workspace-sidebar'); return {innerHeight, "
                                "nav: nav.getBoundingClientRect().toJSON(), "
                                "navClientHeight: nav.clientHeight, "
                                "navScrollHeight: nav.scrollHeight, "
                                "navScrollTop: nav.scrollTop, "
                                "item: item.getBoundingClientRect().toJSON(), "
                                "sidebar: sidebar.getBoundingClientRect().toJSON(), "
                                "sidebarClass: sidebar.className}; }"
                            )
                            raise RuntimeError(
                                "WEB-BROWSER-NAVIGATION: click failed at "
                                f"{viewport}; layout={navigation_layout}"
                            ) from error
                        capability_item = page.locator("li.capability-item").filter(
                            has_text="creator.scene.reply"
                        )
                        capability_item.get_by_role(
                            "button", name="设置更严格限制", exact=True
                        ).click()
                        maximum_uses = capability_item.get_by_label("最大次数")
                        maximum_uses.press("Control+A")
                        maximum_uses.press("2")
                        maximum_uses.press("Enter")
                        capability_item.get_by_text("limited", exact=True).wait_for()
                        capability_item.get_by_text("2/2 次").wait_for()
                        codex_item = page.locator("li.capability-item").filter(
                            has_text="codex.delegated-work"
                        )
                        if codex_item.get_by_role(
                            "button", name="允许申请范围", exact=True
                        ).count():
                            raise RuntimeError(
                                "WEB-BROWSER-CAPABILITY: unavailable Codex can be granted"
                            )
                        if (
                            QuietHandler.timeline_reads < 2
                            or QuietHandler.event_streams < 1
                        ):
                            raise RuntimeError(
                                "WEB-BROWSER-SSE: invalidation did not refetch "
                                "the authoritative timeline"
                            )
                        if mobile_menu.is_visible():
                            mobile_menu.click()
                        page.get_by_role(
                            "button", name="运行与维护", exact=True
                        ).click()
                        with page.expect_response(
                            lambda item: item.url.endswith("/v1/runtime/status")
                        ):
                            page.locator(".session-summary").get_by_role(
                                "button", name="重新读取状态"
                            ).click()
                        if page.get_by_text("ready").count() != 3:
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
                        if mobile_menu.is_visible():
                            mobile_menu.click()
                        page.get_by_role("button", name="对话", exact=True).click()
                        message = "精确保留的 Creator 输入"
                        page.get_by_label("输入内容").fill(message)
                        page.get_by_role("button", name="提交输入").click()
                        page.get_by_text("消息已发送", exact=True).wait_for()
                        page.get_by_role("button", name="详情", exact=True).click()
                        page.locator("dd:visible").filter(
                            has_text=QuietHandler.opportunity_id
                        ).wait_for()
                        effect_trigger = page.get_by_role("button", name="查看效果详情")
                        effect_trigger.wait_for()
                        if QuietHandler.effect_reads != 0:
                            raise RuntimeError(
                                "SEC-WEB-EFFECT: response was fetched before explicit open"
                            )
                        effect_trigger.click()
                        page.get_by_role(
                            "heading", name="已核验回应", exact=True
                        ).wait_for()
                        page.get_by_text(
                            "<img src=https://outside.invalid/x> 已核验回应"
                        ).wait_for()
                        if QuietHandler.effect_reads != 1:
                            raise RuntimeError(
                                "WEB-BROWSER-EFFECT: explicit detail read count was "
                                f"{QuietHandler.effect_reads}; "
                                f"top={Counter(requests).most_common(5)}"
                            )
                        if page.locator(".verified-response img").count():
                            raise RuntimeError(
                                "SEC-WEB-EFFECT-HTML: response created active markup"
                            )
                        close_detail = page.get_by_role("button", name="关闭详情")
                        if not close_detail.evaluate(
                            "element => element === document.activeElement"
                        ):
                            raise RuntimeError(
                                "WEB-BROWSER-FOCUS: effect detail did not receive focus"
                            )
                        close_detail.click()
                        page.wait_for_function(
                            "() => document.activeElement?.textContent"
                            ".includes('查看效果详情')"
                        )
                        if message in page.content():
                            raise RuntimeError(
                                "SEC-WEB-MESSAGE-DOM: accepted body remained visible"
                            )
                        if "creator-input-v1." in json.dumps(storage):
                            raise RuntimeError(
                                "SEC-WEB-IDEMPOTENCY-STORAGE: intent key persisted"
                            )
                        page.reload(wait_until="domcontentloaded")
                        page.get_by_text("本机连接正常").wait_for(state="attached")
                        page.get_by_text("browser.event").wait_for()
                        overflow = page.evaluate(
                            "() => document.documentElement.scrollWidth > "
                            "document.documentElement.clientWidth"
                        )
                        if overflow:
                            raise RuntimeError(
                                "WEB-BROWSER-OVERFLOW: horizontal overflow detected"
                            )
                        cdp = page.context.new_cdp_session(page)
                        cdp.send(
                            "Emulation.setPageScaleFactor",
                            {"pageScaleFactor": 2},
                        )
                        zoom_overflow = page.evaluate(
                            "() => document.documentElement.scrollWidth > "
                            "document.documentElement.clientWidth"
                        )
                        cdp.send(
                            "Emulation.setPageScaleFactor",
                            {"pageScaleFactor": 1},
                        )
                        cdp.detach()
                        if zoom_overflow:
                            raise RuntimeError(
                                "WEB-BROWSER-ZOOM: 200 percent zoom overflow detected"
                            )
                        if any(not request.startswith(origin) for request in requests):
                            raise RuntimeError(
                                "SEC-WEB-REQUEST: external browser request detected"
                            )
                        if len(requests) > 100 or QuietHandler.event_streams > 10:
                            raise RuntimeError(
                                "WEB-BROWSER-REQUEST-STORM: excessive same-origin "
                                f"requests detected; total={len(requests)}, "
                                f"streams={QuietHandler.event_streams}, "
                                f"top={Counter(requests).most_common(5)}"
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
                                "top_requests": Counter(requests).most_common(3),
                                "horizontal_overflow": False,
                                "session_flow": "pass",
                                "event_stream": "pass",
                                "creator_input_loop": "pass",
                                "capability_effect_loop": "pass",
                                "zoom_200_percent": "pass",
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
                "viewports": results,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
