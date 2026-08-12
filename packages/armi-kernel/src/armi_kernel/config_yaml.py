"""Small strict YAML subset for human-maintained ARMI configuration."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_INTEGER = re.compile(r"^-?(?:0|[1-9][0-9]*)$")
_FLOAT = re.compile(r"^-?(?:0|[1-9][0-9]*)\.[0-9]+$")


@dataclass(frozen=True, slots=True)
class _Line:
    number: int
    indent: int
    content: str


def load_yaml_mapping(raw: bytes) -> dict[str, Any]:
    """Parse the deliberately small YAML subset accepted by ARMI configs."""

    try:
        text = raw.decode("utf-8", "strict")
    except UnicodeDecodeError as error:
        raise ValueError("YAML is not UTF-8") from error
    if text.startswith("\ufeff") or "\t" in text:
        raise ValueError("YAML BOM and tabs are not allowed")
    stripped = text.strip()
    if stripped.startswith("{"):
        try:
            value = json.loads(stripped)
        except json.JSONDecodeError as error:
            raise ValueError("invalid JSON-compatible YAML") from error
        if type(value) is not dict or any(type(key) is not str for key in value):
            raise ValueError("YAML root must be a mapping")
        return value
    lines: list[_Line] = []
    for number, original in enumerate(text.splitlines(), 1):
        content = _strip_comment(original).rstrip()
        if not content.strip():
            continue
        indent = len(content) - len(content.lstrip(" "))
        if indent % 2:
            raise ValueError(f"YAML indentation is invalid at line {number}")
        body = content[indent:]
        if body.startswith(("---", "...", "&", "*", "!")):
            raise ValueError("advanced YAML features are not allowed")
        lines.append(_Line(number, indent, body))
    if not lines:
        raise ValueError("YAML document is empty")
    value, index = _parse_block(lines, 0, lines[0].indent)
    if index != len(lines) or type(value) is not dict:
        raise ValueError("YAML root must be a mapping")
    return value


def load_yaml_file(path: Path, *, maximum_bytes: int = 1_048_576) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink() or path.stat().st_size > maximum_bytes:
        raise ValueError("YAML configuration file is unavailable")
    return load_yaml_mapping(path.read_bytes())


def _parse_block(lines: list[_Line], index: int, indent: int) -> tuple[Any, int]:
    if lines[index].indent != indent:
        raise ValueError(f"YAML indentation is invalid at line {lines[index].number}")
    if lines[index].content.startswith("-"):
        return _parse_list(lines, index, indent)
    return _parse_mapping(lines, index, indent)


def _parse_mapping(
    lines: list[_Line], index: int, indent: int
) -> tuple[dict[str, Any], int]:
    result: dict[str, Any] = {}
    while index < len(lines) and lines[index].indent == indent:
        line = lines[index]
        if line.content.startswith("-"):
            break
        key_text, value_text = _split_pair(line)
        key = _parse_key(key_text, line.number)
        if key in result:
            raise ValueError(f"duplicate YAML key at line {line.number}")
        index += 1
        if value_text:
            result[key] = _parse_scalar(value_text, line.number)
        elif index < len(lines) and lines[index].indent > indent:
            result[key], index = _parse_block(lines, index, lines[index].indent)
        else:
            result[key] = None
    return result, index


def _parse_list(lines: list[_Line], index: int, indent: int) -> tuple[list[Any], int]:
    result: list[Any] = []
    while index < len(lines) and lines[index].indent == indent:
        line = lines[index]
        if not line.content.startswith("-"):
            break
        rest = line.content[1:].strip()
        index += 1
        if not rest:
            if index >= len(lines) or lines[index].indent <= indent:
                raise ValueError(f"YAML list item is empty at line {line.number}")
            value, index = _parse_block(lines, index, lines[index].indent)
            result.append(value)
            continue
        if _find_colon(rest) is None:
            result.append(_parse_scalar(rest, line.number))
            continue
        key_text, value_text = _split_text_pair(rest, line.number)
        item = {_parse_key(key_text, line.number): _parse_scalar(value_text, line.number)}
        if index < len(lines) and lines[index].indent > indent:
            continuation, index = _parse_mapping(lines, index, lines[index].indent)
            if item.keys() & continuation.keys():
                raise ValueError(f"duplicate YAML key near line {line.number}")
            item.update(continuation)
        result.append(item)
    return result, index


def _split_pair(line: _Line) -> tuple[str, str]:
    return _split_text_pair(line.content, line.number)


def _split_text_pair(value: str, number: int) -> tuple[str, str]:
    position = _find_colon(value)
    if position is None:
        raise ValueError(f"YAML mapping entry is invalid at line {number}")
    return value[:position].strip(), value[position + 1 :].strip()


def _find_colon(value: str) -> int | None:
    quote: str | None = None
    for index, character in enumerate(value):
        if character in {'"', "'"}:
            quote = None if quote == character else character if quote is None else quote
        elif character == ":" and quote is None:
            return index
    return None


def _parse_key(value: str, number: int) -> str:
    parsed = _parse_scalar(value, number)
    if type(parsed) is not str or not parsed:
        raise ValueError(f"YAML mapping key must be text at line {number}")
    return parsed


def _parse_scalar(value: str, number: int) -> Any:
    if not value:
        return None
    if value.startswith(("&", "*", "!")):
        raise ValueError("advanced YAML features are not allowed")
    if value.startswith('"'):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as error:
            raise ValueError(f"invalid quoted YAML value at line {number}") from error
        if type(parsed) is not str:
            raise ValueError(f"invalid YAML string at line {number}")
        return parsed
    if value.startswith("'"):
        if len(value) < 2 or not value.endswith("'"):
            raise ValueError(f"invalid quoted YAML value at line {number}")
        return value[1:-1].replace("''", "'")
    if value in {"true", "false"}:
        return value == "true"
    if value in {"null", "~"}:
        return None
    if _INTEGER.fullmatch(value):
        return int(value)
    if _FLOAT.fullmatch(value):
        return float(value)
    if value.startswith(("[", "{")):
        try:
            return json.loads(value)
        except json.JSONDecodeError as error:
            raise ValueError(f"invalid inline YAML value at line {number}") from error
    return value


def _strip_comment(value: str) -> str:
    quote: str | None = None
    for index, character in enumerate(value):
        if character in {'"', "'"}:
            quote = None if quote == character else character if quote is None else quote
        elif character == "#" and quote is None and (index == 0 or value[index - 1].isspace()):
            return value[:index]
    return value


__all__ = ("load_yaml_file", "load_yaml_mapping")
