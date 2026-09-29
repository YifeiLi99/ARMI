"""Source dialogue lab. Uses formal Admin/Interaction interfaces, never installed data."""

# ruff: noqa: RUF001 -- Chinese CLI text.

from __future__ import annotations

import argparse
import asyncio
import getpass
import io
import json
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid7

import httpx
from armi_admin.application import (
    AdminConfigError,
    AdminCredentialPort,
    load_admin_config,
)
from armi_admin.application.catalog import ADMIN_OPERATIONS
from armi_admin.application.installation import SetupError
from armi_admin.composition import bootstrap_admin
from armi_kernel.application import BirthViolation
from armi_local_control import (
    ConfigurationViolation,
    RuntimeViolation,
    private_directory,
)
from armi_local_control.binding import load_client_binding
from armi_runtime.interaction_client import InteractionClient

from tools.dialogue_lab_support import ROOT, LabError, save


class DialogueLab:
    @contextmanager
    def admin_session(self):
        """Keep the formal CLI/MCP application and its bound role pool open."""
        config = self.config
        credentials = AdminCredentialPort(
            locator=config.locator,
            migrator_locator=config.migrator_locator,
            preview_locator=config.preview_locator,
            authorization_locator=config.authorization_signing_key_locator,
            config_root=self.root,
        )
        composition = bootstrap_admin(config, credentials)
        self._admin_service = composition.service
        try:
            yield
        finally:
            self._admin_service = None
            composition.close()

    def __init__(self, root: Path) -> None:
        self.root = root.resolve(strict=True)
        self.config, _ = load_admin_config(
            {"ARMI_ADMIN_CONFIG": str(self.root / "admin.yaml")}
        )
        self.config.expected.verify()
        if (
            self.config.environment_kind.value != "system_test"
            or not self.config.test_controls_enabled
            or self.config.environment_root.resolve() != self.root
            or self.config.expected.source_root is None
        ):
            raise LabError("LAB-SOURCE-TEST-ENVIRONMENT-REQUIRED")
        self.binding = load_client_binding(self.root / "client.yaml")
        if (
            self.binding.environment_root.resolve() != self.root
            or str(self.binding.environment_id) != self.config.environment_id
        ):
            raise LabError("LAB-CLIENT-BINDING-MISMATCH")

    def admin(
        self, name: str, arguments: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        receipt = None
        if arguments and arguments.get("idempotency_key"):
            directory = self.root / "invocations"
            private_directory(directory)
            receipt = directory / f"{uuid7()}.json"
            save(
                receipt,
                {"operation": name, "arguments": arguments, "status": "dispatching"},
            )
        command = name.replace("_", "-").split()
        if name.startswith(("autonomy_", "usage_", "invocation_")):
            command = name.split("_", 1)
        elif name.startswith("environment_") and name in {
            "environment_start",
            "environment_stop",
            "environment_status",
        }:
            command = [name.removeprefix("environment_")]
        if getattr(self, "_admin_service", None) is not None:
            assert self._admin_service is not None
            operation = next(item for item in ADMIN_OPERATIONS if item.name == name)
            bound = dict(arguments or {})
            bound["environment_id"] = self.config.environment_id
            if operation.mode in {"mutate", "lifecycle"}:
                bound["environment_incarnation"] = self.config.environment_incarnation
                bound["purpose"] = f"admin.{name}"
            if operation.mode == "lifecycle":
                bound["component"] = "environment"
            result = operation.invoke(
                self._admin_service,
                operation.request.model_validate_json(json.dumps(bound)),
            ).model_dump(mode="json")
            if receipt is not None:
                save(
                    receipt,
                    {"operation": name, "arguments": arguments, "response": result},
                )
            if result["status"] != "succeeded":
                raise LabError(
                    f"LAB-ADMIN-{name}: {result.get('error_code', 'unknown')}"
                )
            return result["result"]
        call = subprocess.run(
            [
                sys.executable,
                "-X",
                "utf8",
                "-m",
                "armi_app",
                "cli",
                "admin",
                "--config",
                str(self.root / "admin.yaml"),
                *command,
                "--json",
                json.dumps(arguments or {}),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=360,
        )
        try:
            result = json.loads(call.stdout)
        except ValueError:
            raise LabError("LAB-ADMIN-TRANSPORT") from None
        if receipt is not None:
            save(
                receipt, {"operation": name, "arguments": arguments, "response": result}
            )
        if call.returncode or result.get("status") != "succeeded":
            raise LabError(f"LAB-ADMIN-{name}: {result.get('error_code', 'unknown')}")
        return result["result"]

    def status(self) -> dict[str, Any]:
        runtime = self.admin("runtime_status")
        # A stopped lab may also have a stopped database; do not query its projections.
        if runtime["status"] != "running":
            autonomy = {
                "status": "unavailable",
                "reason": "runtime_" + runtime["status"],
            }
        else:
            autonomy = self.admin("autonomy_status")
        return {"runtime": runtime, "autonomy": autonomy}

    def capture(
        self, *, interaction_id: str | None = None, episode_id: str | None = None
    ) -> Path:
        directory = self.root / "captures" / str(uuid7())
        private_directory(directory)
        # Keep partial evidence on failure; never claim that a partial export is complete.
        save(
            directory / "capture.json",
            {"status": "collecting", "environment_id": self.config.environment_id},
        )
        selector = (
            {"interaction_id": interaction_id}
            if interaction_id
            else {"episode_id": episode_id}
        )
        episodes: set[str] = set()
        cursor = None
        page = 0
        truncated = False
        while True:
            graph = self.admin(
                "trace_flow",
                {**selector, "limit": 100, **({"cursor": cursor} if cursor else {})},
            )
            save(directory / f"trace-{page}.json", graph)
            truncated |= bool(graph.get("expansion_truncated"))
            related = {key: [value] for key, value in selector.items()}
            names = {
                "episode": "episode_id",
                "input": "interaction_id",
                "effect": "effect_id",
                "work": "work_id",
                "provider_call": "call_id",
                "opportunity": "opportunity_id",
            }
            for node in graph["nodes"]:
                if node["kind"] in names:
                    related.setdefault(names[node["kind"]], []).append(node["id"])
            related = {
                key: list(dict.fromkeys(values)) for key, values in related.items()
            }
            # Each graph page is bounded; use its explicit identity filter on every
            # diagnostics cursor page (the cursor is bound to that exact filter).
            diagnostics = self.admin(
                "diagnostics_query", {"related_ids": related, "limit": 200}
            )
            diagnostic_page = 0
            while diagnostics:
                save(
                    directory / f"diagnostics-{page}-{diagnostic_page}.json",
                    diagnostics,
                )
                for item in diagnostics.get("items", []):
                    if item.get("log_ref"):
                        evidence = self.admin(
                            "diagnostics_read", {"log_ref": item["log_ref"]}
                        )
                        save(
                            directory
                            / f"diagnostic-{page}-{diagnostic_page}-{uuid7()}.json",
                            evidence,
                        )
                cursor_log = diagnostics.get("cursor")
                if not cursor_log:
                    break
                diagnostics = self.admin(
                    "diagnostics_query",
                    {"related_ids": related, "limit": 200, "cursor": cursor_log},
                )
                diagnostic_page += 1
            for node in graph["nodes"]:
                if node["kind"] in {"episode", "cognitive_episode"}:
                    episodes.add(node["id"])
            cursor = graph.get("cursor")
            page += 1
            if not cursor:
                break
        if episode_id:
            episodes.add(episode_id)
        for identity in sorted(episodes):
            detail = self.admin("cognition_read", {"episode_id": identity})
            save(directory / f"episode-{identity}.json", detail)
            for artifact in detail["artifacts"]:
                if not artifact["retained"]:
                    continue
                offset = 0
                parts: list[str] = []
                while True:
                    chunk = self.admin(
                        "cognition_read",
                        {
                            "episode_id": identity,
                            "artifact_id": artifact["artifact_id"],
                            "offset": offset,
                            "length": 65536,
                        },
                    )["text"]
                    parts.append(chunk["content"])
                    next_offset = chunk["next_offset"]
                    if next_offset is None:
                        break
                    if next_offset <= offset:
                        raise LabError("LAB-ARTIFACT-PAGINATION")
                    offset = next_offset
                (
                    directory / f"{artifact['role']}-{artifact['artifact_id']}.txt"
                ).write_text("".join(parts), encoding="utf-8")
            # Jev actual request/response and frozen appraisal evidence are retained
            # by the event owner, separately from main-model cognition attempts.
            appraisal = self.admin(
                "database_query",
                {
                    "table": "event_appraisals",
                    "filters": [
                        {
                            "field": "cognitive_episode_id",
                            "operator": "eq",
                            "value": identity,
                        }
                    ],
                    "limit": 200,
                },
            )
            save(directory / f"appraisal-{identity}.json", appraisal)
        save(directory / "autonomy.json", self.admin("autonomy_status"))
        save(
            directory / "capture.json",
            {
                "status": "partial" if truncated else "collected",
                "environment_id": self.config.environment_id,
                "episodes": sorted(episodes),
                "interaction_id": interaction_id,
                "real_model_execution": "see retained attempt results; capture does not execute models",
            },
        )
        return directory

    async def message(self, message: str, timeout: float) -> dict[str, Any]:
        if not 0 < timeout <= 3600:
            raise LabError("LAB-TIMEOUT-RANGE")
        client = InteractionClient(self.binding)
        key = f"lab-{uuid7()}"
        turn = self.root / "turns" / key
        private_directory(turn)
        save(turn / "input.json", {"message": message, "idempotency_key": key})
        accepted = await client.invoke(
            "message_send",
            {"scene_key": "default", "message": message, "idempotency_key": key},
        )
        save(turn / "accepted.json", accepted)
        if accepted.get("transport_status") != 202:
            raise LabError("LAB-INPUT-REJECTED")
        details = accepted["result"]["details"]
        reference = details["opportunity_id"]
        deadline = time.monotonic() + timeout
        result: dict[str, Any] = {}
        while time.monotonic() < deadline:
            result = await client.wait(
                reference,
                timeout_seconds=min(25, max(0.1, deadline - time.monotonic())),
            )
            if result.get("wait_status") != "timeout":
                break
        save(turn / "outcome.json", result)
        effect_id = result.get("result", {}).get("details", {}).get("effect_ref")
        reply = None
        if effect_id:
            effect = await client.invoke("effect_get", {"effect_id": effect_id})
            save(turn / "effect.json", effect)
            reply = effect.get("result", {}).get("response_text")
        capture = self.capture(interaction_id=details["interaction_id"])
        return {
            "reply": reply,
            "operation": result,
            "capture": str(capture),
            "turn": str(turn),
            "interaction_id": details["interaction_id"],
        }

    def watch(self, seconds: int) -> dict[str, Any]:
        if not 0 <= seconds <= 3600:
            raise LabError("LAB-WATCH-RANGE")
        deadline = time.monotonic() + seconds
        seen: set[str] = set()
        captures: list[str] = []
        while True:
            offset = 0
            while True:
                page = self.admin(
                    "database_query",
                    {
                        "table": "cognitive_episodes",
                        "fields": ["cognitive_episode_id", "status"],
                        "filters": [
                            {
                                "field": "status",
                                "operator": "in",
                                "value": [
                                    "candidate_rejected",
                                    "completed",
                                    "stale",
                                    "failed",
                                    "cancelled",
                                ],
                            }
                        ],
                        "limit": 200,
                        "offset": offset,
                    },
                )
                for row in page["rows"]:
                    identity = row["values"]["cognitive_episode_id"]
                    if identity not in seen:
                        capture = self.capture(episode_id=identity)
                        captures.append(str(capture))
                        seen.add(identity)
                        print(
                            json.dumps(
                                {"episode_id": identity, "capture": str(capture)},
                                ensure_ascii=False,
                            ),
                            flush=True,
                        )
                next_offset = page["next_offset"]
                if next_offset is None:
                    break
                offset = next_offset
            if time.monotonic() >= deadline:
                return {"captures": captures, "autonomy": self.admin("autonomy_status")}
            time.sleep(max(0, min(5, deadline - time.monotonic())))


def main() -> int:
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    initialize = commands.add_parser(
        "init", help="Create a NEW source test environment; no model calls"
    )
    initialize.add_argument("--anchor", type=Path, required=True)
    initialize.add_argument("--creator-resources", type=Path, required=True)
    for name in ("status", "stop"):
        commands.add_parser(name)
    credential = commands.add_parser("credential")
    credential.add_argument(
        "--name",
        choices=("mood.jev_api_key", "model.qwen_api_key", "model.deepseek_api_key"),
        required=True,
    )
    start = commands.add_parser("start")
    start.add_argument(
        "--live",
        action="store_true",
        required=True,
        help="Allow configured real providers in this test environment",
    )
    message = commands.add_parser("send")
    message.add_argument("--message", required=True)
    message.add_argument("--timeout", type=float, default=240)
    chat = commands.add_parser("chat")
    chat.add_argument("--timeout", type=float, default=240)
    advance = commands.add_parser("advance")
    advance.add_argument("--seconds", type=int, required=True)
    watch = commands.add_parser(
        "watch",
        help="Capture completed dialogue/autonomy episodes, including existing ones",
    )
    watch.add_argument("--seconds", type=int, default=300)
    simulate = commands.add_parser(
        "simulate",
        help="Run the real chain with idle time injection and a complete usage report",
    )
    simulate.add_argument("--seconds", type=int, default=600)
    simulate.add_argument("--live", action="store_true", required=True)
    capture = commands.add_parser("capture")
    selectors = capture.add_mutually_exclusive_group(required=True)
    selectors.add_argument("--interaction-id")
    selectors.add_argument("--episode-id")
    args = parser.parse_args()
    try:
        if args.command == "init":
            from tools.dialogue_lab_environment import initialize

            result = initialize(
                args.root, anchor=args.anchor, creator_resources=args.creator_resources
            )
        else:
            lab = DialogueLab(args.root)
            if args.command == "simulate":
                from tools.dialogue_lab_simulation import simulate

                result = simulate(lab, seconds=args.seconds)
            elif args.command == "credential":
                from armi_admin.application.installation import store_provider_secret
                from armi_local_control.runtime_process import LocalProcessLock

                with LocalProcessLock(lab.root / "credential.lock"):
                    value = getpass.getpass("API key（输入不回显）: ").encode("utf-8")
                    store_provider_secret(lab.root, args.name, value)
                result = {"status": "saved", "name": args.name, "verified": False}
            elif args.command in {"start", "stop"}:
                result = lab.admin(
                    "environment_" + args.command, {"idempotency_key": str(uuid7())}
                )
            elif args.command == "status":
                result = lab.status()
            elif args.command == "advance":
                result = lab.admin(
                    "advance_test_time",
                    {"seconds": args.seconds, "idempotency_key": str(uuid7())},
                )
            elif args.command == "capture":
                result = {
                    "capture": str(
                        lab.capture(
                            interaction_id=args.interaction_id,
                            episode_id=args.episode_id,
                        )
                    )
                }
            elif args.command == "watch":
                result = lab.watch(args.seconds)
            elif args.command == "send":
                result = asyncio.run(lab.message(args.message, args.timeout))
            else:
                print(
                    "输入对话；/status 查看状态，/advance 秒数 跳时，/watch 秒数 抓取主动轮次，/quit 退出并停止测试环境。"
                )
                try:
                    while True:
                        text = input("你 > ").strip()
                        if text == "/quit":
                            break
                        if text == "/status":
                            result = lab.status()
                        elif text.startswith("/advance "):
                            result = lab.admin(
                                "advance_test_time",
                                {
                                    "seconds": int(text.split()[1]),
                                    "idempotency_key": str(uuid7()),
                                },
                            )
                        elif text.startswith("/watch "):
                            result = lab.watch(int(text.split()[1]))
                        elif text:
                            result = asyncio.run(lab.message(text, args.timeout))
                        else:
                            continue
                        print(json.dumps(result, ensure_ascii=False, indent=2))
                finally:
                    lab.admin("environment_stop", {"idempotency_key": str(uuid7())})
                return 0
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except KeyboardInterrupt, EOFError:
        print(json.dumps({"status": "interrupted"}))
        return 130
    except (
        LabError,
        ValueError,
        OSError,
        AdminConfigError,
        SetupError,
        BirthViolation,
        ConfigurationViolation,
        RuntimeViolation,
        httpx.HTTPError,
        subprocess.TimeoutExpired,
    ) as error:
        # Never print provider credentials, subprocess stderr or config contents.
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error": str(error)
                    if isinstance(error, LabError)
                    else getattr(error, "code", type(error).__name__),
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
