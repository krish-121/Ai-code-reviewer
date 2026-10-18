"""Validate tool completion separately from filtering useful diagnostics."""

from __future__ import annotations

import json
import re


def output_error(tool: str, code: int, stdout: str, stderr: str) -> str:
    """Return why output cannot establish a successful analysis, or an empty string."""
    accepted = {0, 1, 2} if tool == "tsc" else {0, 1}
    if code not in accepted:
        return f"tool exited with {code}: {stderr[:250]}"
    try:
        if tool in {"ruff", "eslint", "bandit"}:
            return _json_error(tool, stdout)
        if tool == "mypy":
            return _mypy_error(code, stdout)
        if tool == "tsc":
            lines = stdout.splitlines()
            valid = all(
                re.match(r"^.+\(\d+,\d+\): error TS\d+:", line) for line in lines if line.strip()
            )
            if not valid or (code and not stdout.strip()) or stderr.strip():
                return "TypeScript failed without complete file diagnostics"
    except (ValueError, TypeError, KeyError):
        return "invalid diagnostic output"
    return ""


def _json_error(tool: str, stdout: str) -> str:
    data = json.loads(stdout)
    if tool == "bandit":
        if not isinstance(data, dict) or not isinstance(data.get("results"), list):
            return "invalid Bandit report"
        if not _has_fields(data["results"], {"test_id", "filename", "line_number", "issue_text"}):
            return "invalid Bandit diagnostic"
        return "Bandit could not analyze every file" if data.get("errors") else ""
    if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
        return "invalid diagnostic list"
    if tool == "eslint":
        return _eslint_error(data)
    if tool == "ruff":
        required = {"filename", "message", "location"}
        if any(not required <= item.keys() for item in data):
            return "invalid Ruff diagnostic"
    return ""


def _has_fields(items: list[object], required: set[str]) -> bool:
    return all(isinstance(item, dict) and required <= item.keys() for item in items)


def _eslint_error(data: list[dict[str, object]]) -> str:
    for item in data:
        messages = item.get("messages")
        if "filePath" not in item or not isinstance(messages, list):
            return "invalid ESLint report"
        if any(not isinstance(msg, dict) for msg in messages):
            return "invalid ESLint messages"
        if item.get("fatalErrorCount") or any(msg.get("fatal") for msg in messages):
            return "ESLint reported a fatal parsing/configuration error"
    return ""


def _mypy_error(code: int, stdout: str) -> str:
    lines = [line for line in stdout.splitlines() if line.strip()]
    if code and not lines:
        return "mypy failed without diagnostics"
    for line in lines:
        if line.startswith("{"):
            item = json.loads(line)
            if not {"file", "line", "message", "severity"} <= item.keys():
                return "invalid mypy diagnostic"
        elif not re.match(r"^.+:\d+:(?:\d+:)? (?:error|note|warning):", line):
            return "unrecognized mypy output"
    return ""
