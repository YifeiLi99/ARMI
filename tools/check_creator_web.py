"""Validate the narrow Creator source, generated, and browser-security boundaries."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SOURCE_SUFFIXES = {".ts", ".tsx", ".css", ".html"}
NETWORK_PATTERN = re.compile(r"\b(?:fetch|XMLHttpRequest)\s*\(")
FORBIDDEN_STREAM_PATTERN = re.compile(r"\b(?:WebSocket|EventSource)\s*\(")
STORAGE_PATTERN = re.compile(
    r"\b(?:localStorage|sessionStorage|indexedDB|document\.cookie|serviceWorker)\b"
)
DYNAMIC_PATTERN = re.compile(r"\b(?:eval|Function)\s*\(|dangerouslySetInnerHTML")
EXTERNAL_PATTERN = re.compile(r"https?://", flags=re.IGNORECASE)
GLOBAL_STORE_PATTERN = re.compile(
    r"\b(?:createStore|globalStore|serviceLocator|serviceRegistry)\b"
)


@dataclass(frozen=True, order=True)
class Violation:
    code: str
    path: str
    line: int
    message: str

    def render(self) -> str:
        return f"{self.path}:{self.line}: {self.code}: {self.message}"


def _line(source: str, offset: int) -> int:
    return source.count("\n", 0, offset) + 1


def _matches(
    source: str,
    *,
    path: str,
    pattern: re.Pattern[str],
    code: str,
    message: str,
) -> list[Violation]:
    return [
        Violation(code, path, _line(source, match.start()), message)
        for match in pattern.finditer(source)
    ]


def validate_policy(policy: dict[str, Any], path: str) -> list[Violation]:
    creator = policy.get("creator_web")
    if not isinstance(creator, dict):
        return [
            Violation(
                "ARC-WEB-POLICY",
                path,
                1,
                "creator_web policy must be an object",
            )
        ]
    violations: list[Violation] = []
    if creator.get("source_root") != "apps/armi-creator-web/src":
        violations.append(
            Violation("ARC-WEB-POLICY", path, 1, "unexpected Creator source root")
        )
    if creator.get("generated_file") != (
        "apps/armi-creator-web/src/api/generated/creator.ts"
    ):
        violations.append(
            Violation("ARC-WEB-POLICY", path, 1, "unexpected generated type path")
        )
    features = creator.get("features")
    if not isinstance(features, list):
        violations.append(
            Violation("ARC-WEB-POLICY", path, 1, "features must be an array")
        )
    elif features != [
        "capability",
        "effect",
        "operation",
        "session",
        "scene",
        "subject",
    ]:
        violations.append(
            Violation(
                "ARC-WEB-FEATURE",
                path,
                1,
                "S031 permits only the single-page capability/effect/operation/session/scene/subject features",
            )
        )
    event_stream = creator.get("event_stream")
    if event_stream != {
        "contract": "creator-event-stream.v2",
        "transport": "authenticated-fetch-sse",
        "client": "apps/armi-creator-web/src/api/eventStream.ts",
        "broker": "armi_runtime.interfaces.creator_events.CreatorEventBroker",
        "fact_source": False,
        "runtime_discovery": False,
        "persistent_event_cache": False,
        "event_kinds": [
            "scene.timeline.invalidated",
            "capability.request.invalidated",
            "operation.invalidated",
            "effect.invalidated",
            "subject.summary.invalidated",
        ],
    }:
        violations.append(
            Violation(
                "ARC-WEB-STREAM",
                path,
                1,
                "Creator SSE boundary must remain explicit and non-authoritative",
            )
        )
    return violations


def analyze_source(source: str, *, path: str) -> list[Violation]:
    if ".test." in path:
        return []
    violations: list[Violation] = []
    if path not in {
        "apps/armi-creator-web/src/api/client.ts",
        "apps/armi-creator-web/src/api/eventStream.ts",
    }:
        violations.extend(
            _matches(
                source,
                path=path,
                pattern=NETWORK_PATTERN,
                code="SEC-WEB-NETWORK",
                message="network activity is allowed only in the explicit API client",
            )
        )
    violations.extend(
        _matches(
            source,
            path=path,
            pattern=FORBIDDEN_STREAM_PATTERN,
            code="SEC-WEB-STREAM",
            message="native EventSource and WebSocket are forbidden",
        )
    )
    if path != "apps/armi-creator-web/src/features/session/storage.ts":
        violations.extend(
            _matches(
                source,
                path=path,
                pattern=STORAGE_PATTERN,
                code="SEC-WEB-STORAGE",
                message="browser storage is allowed only in the session storage adapter",
            )
        )
    elif re.search(
        r"\b(?:localStorage|indexedDB|document\.cookie|serviceWorker)\b",
        source,
    ):
        violations.append(
            Violation(
                "SEC-WEB-STORAGE",
                path,
                1,
                "the session adapter may use sessionStorage only",
            )
        )
    violations.extend(
        _matches(
            source,
            path=path,
            pattern=DYNAMIC_PATTERN,
            code="SEC-WEB-DYNAMIC",
            message="dynamic HTML or code execution is forbidden",
        )
    )
    violations.extend(
        _matches(
            source,
            path=path,
            pattern=EXTERNAL_PATTERN,
            code="SEC-WEB-EXTERNAL",
            message="external URLs are forbidden in Creator source",
        )
    )
    violations.extend(
        _matches(
            source,
            path=path,
            pattern=GLOBAL_STORE_PATTERN,
            code="ARC-WEB-GLOBAL-STORE",
            message="global stores and service locators are forbidden",
        )
    )
    return violations


def check_repository(root: Path) -> list[Violation]:
    root = root.resolve()
    policy_path = root / "tools/architecture-policy.json"
    try:
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return [Violation("ARC-WEB-POLICY", policy_path.as_posix(), 1, str(error))]
    if not isinstance(policy, dict):
        return [
            Violation(
                "ARC-WEB-POLICY",
                policy_path.as_posix(),
                1,
                "policy root must be an object",
            )
        ]
    violations = validate_policy(policy, policy_path.as_posix())
    creator = policy.get("creator_web", {})
    if not isinstance(creator, dict):
        return violations
    source_root = root / str(creator.get("source_root", ""))
    generated = root / str(creator.get("generated_file", ""))
    if not generated.is_file():
        violations.append(
            Violation(
                "ARC-WEB-GENERATED",
                generated.as_posix(),
                1,
                "generated OpenAPI types are missing",
            )
        )
    elif "This file was auto-generated by openapi-typescript." not in (
        generated.read_text(encoding="utf-8")
    ):
        violations.append(
            Violation(
                "ARC-WEB-GENERATED",
                generated.relative_to(root).as_posix(),
                1,
                "generated OpenAPI types lost their generator marker",
            )
        )

    allowed = {"app", "api", "features", "styles", "main.tsx"}
    if source_root.is_dir():
        for child in source_root.iterdir():
            if child.name not in allowed:
                violations.append(
                    Violation(
                        "ARC-WEB-LAYER",
                        child.relative_to(root).as_posix(),
                        1,
                        "unregistered top-level Creator source responsibility",
                    )
                )
        feature_root = source_root / "features"
        if feature_root.is_dir():
            unexpected = sorted(
                child.name
                for child in feature_root.iterdir()
                if child.name
                not in {
                    "capability",
                    "effect",
                    "operation",
                    "scene",
                    "session",
                    "subject",
                }
            )
            for name in unexpected:
                violations.append(
                    Violation(
                        "ARC-WEB-FUTURE",
                        (feature_root / name).relative_to(root).as_posix(),
                        1,
                        "unregistered Creator business feature",
                    )
                )
        for path in sorted(source_root.rglob("*")):
            if not path.is_file() or path.suffix not in SOURCE_SUFFIXES:
                continue
            relative = path.relative_to(root).as_posix()
            if path == generated:
                continue
            violations.extend(
                analyze_source(path.read_text(encoding="utf-8"), path=relative)
            )
    return sorted(set(violations))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    args = parser.parse_args()
    violations = check_repository(args.root)
    if violations:
        for violation in violations:
            print(violation.render())
        print(f"creator-web-boundaries: fail ({len(violations)} violation(s))")
        return 1
    print("creator-web-boundaries: pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
