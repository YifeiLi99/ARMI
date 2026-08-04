"""Scan repository candidates and build smoke outputs for unsafe text."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

TEXT_SUFFIXES = {
    "",
    ".css",
    ".html",
    ".js",
    ".json",
    ".md",
    ".mjs",
    ".npmrc",
    ".ps1",
    ".py",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}
PATTERNS = (
    (
        "SEC-SECRET-PRIVATE-KEY",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
        "private key material",
    ),
    (
        "SEC-SECRET-TOKEN",
        re.compile(
            r"(?<![A-Za-z0-9])(?:sk|ghp|github_pat|xox[baprs])-"
            r"[A-Za-z0-9_-]{20,}"
        ),
        "high-confidence token",
    ),
    (
        "SEC-SECRET-CREDENTIAL",
        re.compile(
            r"(?i)(?:api[_-]?key|access[_-]?token|client[_-]?secret|password)"
            r"\s*[:=]\s*[\"'][^\"'\s]{8,}[\"']"
        ),
        "credential-like assignment",
    ),
    (
        "SEC-SECRET-URL-CREDENTIAL",
        re.compile(r"(?i)https?://[^/\s:@]+:[^/\s@]+@"),
        "credential embedded in URL",
    ),
    (
        "SEC-PATH-PERSONAL",
        re.compile(r"(?i)(?:[A-Z]:\\Users\\[^\\\s]+|/ho" r"me/[^/\s]+)"),
        "personal absolute path",
    ),
)


@dataclass(frozen=True, order=True)
class Violation:
    code: str
    path: str
    line: int
    message: str

    def render(self) -> str:
        return f"{self.path}:{self.line}: {self.code}: {self.message}"


def git_candidate_paths(root: Path) -> list[Path]:
    result = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        return sorted(path for path in root.rglob("*") if path.is_file())
    return [
        root / line
        for line in result.stdout.splitlines()
        if line and (root / line).is_file()
    ]


def text_paths(paths: Iterable[Path]) -> Iterable[Path]:
    for path in paths:
        if (
            path.name
            in {
                ".gitattributes",
                ".gitignore",
                ".node-version",
                ".python-version",
            }
            or path.suffix.lower() in TEXT_SUFFIXES
        ):
            yield path


def relative_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def scan_paths(paths: Iterable[Path], root: Path) -> list[Violation]:
    violations: list[Violation] = []
    for path in sorted(set(text_paths(paths))):
        relative = relative_path(path, root)
        try:
            raw = path.read_bytes()
            text = raw.decode("utf-8")
        except (OSError, UnicodeError) as error:
            violations.append(
                Violation("SEC-TEXT-UTF8", relative, 1, f"invalid UTF-8 text: {error}")
            )
            continue
        if raw.startswith(b"\xef\xbb\xbf"):
            violations.append(
                Violation("SEC-TEXT-UTF8", relative, 1, "UTF-8 BOM is forbidden")
            )
        if b"\r" in raw:
            violations.append(
                Violation("SEC-TEXT-LF", relative, 1, "CR/CRLF is forbidden")
            )
        if path.suffix.lower() == ".json" and len(text.splitlines()) < 2:
            violations.append(
                Violation(
                    "REP-JSON-FORMAT",
                    relative,
                    1,
                    "committed JSON must use readable multi-line formatting",
                )
            )
        for code, pattern, message in PATTERNS:
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                violations.append(Violation(code, relative, line, message))
    return sorted(set(violations))


def check_repository(root: Path, extra_paths: Iterable[Path] = ()) -> list[Violation]:
    root = root.resolve()
    paths = git_candidate_paths(root)
    for extra in extra_paths:
        resolved = extra if extra.is_absolute() else root / extra
        if resolved.is_file():
            paths.append(resolved)
        elif resolved.is_dir():
            paths.extend(path for path in resolved.rglob("*") if path.is_file())
    return scan_paths(paths, root)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--path", type=Path, action="append", default=[])
    args = parser.parse_args()
    violations = check_repository(args.root, args.path)
    if violations:
        for violation in violations:
            print(violation.render(), file=sys.stderr)
        return 1
    print("repository-hygiene: pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
