"""Validate review packet artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .validation import ValidationMessage


REQUIRED_MARKDOWN_SECTIONS = (
    "# Review Packet",
    "## Issue",
    "## Pull Request",
    "## Summary",
    "## Changed files",
    "## Tests run",
    "## CI status",
    "## Known risks",
    "## Human review checklist",
)


def validate_review_packet(path: Path) -> list[ValidationMessage]:
    path = path.resolve()
    messages: list[ValidationMessage] = []
    if not path.is_file():
        return [ValidationMessage("ERROR", path, "review packet file is missing")]
    if path.suffix.lower() == ".json":
        messages.extend(_validate_json_packet(path))
        return messages
    messages.extend(_validate_markdown_packet(path))
    sibling_json = path.with_suffix(".json")
    if sibling_json.is_file():
        messages.extend(_validate_json_packet(sibling_json))
    return messages


def _validate_markdown_packet(path: Path) -> list[ValidationMessage]:
    text = path.read_text(encoding="utf-8")
    messages: list[ValidationMessage] = []
    for section in REQUIRED_MARKDOWN_SECTIONS:
        if section not in text:
            messages.append(ValidationMessage("ERROR", path, f"review packet is missing section: {section}"))
    return messages


def _validate_json_packet(path: Path) -> list[ValidationMessage]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [ValidationMessage("ERROR", path, f"review packet JSON is invalid: {exc}")]
    if not isinstance(payload, dict):
        return [ValidationMessage("ERROR", path, "review packet JSON must be an object")]
    messages: list[ValidationMessage] = []
    messages.extend(_require_object(path, payload, "issue"))
    issue = payload.get("issue")
    messages.extend(_require_string(path, issue, "identifier", label="issue.identifier"))
    messages.extend(_require_string(path, issue, "title", label="issue.title"))
    messages.extend(_require_string(path, issue, "url", label="issue.url"))
    messages.extend(_require_object(path, payload, "pull_request"))
    pull_request = payload.get("pull_request")
    messages.extend(_require_string(path, pull_request, "url", label="pull_request.url"))
    messages.extend(_require_string(path, pull_request, "status", label="pull_request.status"))
    messages.extend(_require_string(path, payload, "summary"))
    messages.extend(_require_list(path, payload, "changed_files"))
    messages.extend(_require_tests(path, payload.get("tests")))
    messages.extend(_require_object(path, payload, "ci"))
    messages.extend(_require_string(path, payload.get("ci"), "status", label="ci.status"))
    messages.extend(_require_object(path, payload, "artifacts"))
    artifacts = payload.get("artifacts")
    for field in ("screenshots", "videos", "logs", "metrics"):
        messages.extend(_require_list(path, artifacts, field, label=f"artifacts.{field}"))
    messages.extend(_require_list(path, payload, "risks"))
    messages.extend(_require_list(path, payload, "follow_ups"))
    return messages


def _require_object(path: Path, payload: Any, field: str) -> list[ValidationMessage]:
    value = _field_value(payload, field)
    if not isinstance(value, dict):
        return [ValidationMessage("ERROR", path, f"review packet JSON field must be an object: {field}")]
    return []


def _require_string(path: Path, payload: Any, field: str, *, label: str | None = None) -> list[ValidationMessage]:
    value = _field_value(payload, field)
    if not isinstance(value, str) or not value.strip():
        return [ValidationMessage("ERROR", path, f"review packet JSON field must be a non-empty string: {label or field}")]
    return []


def _require_list(path: Path, payload: Any, field: str, *, label: str | None = None) -> list[ValidationMessage]:
    value = _field_value(payload, field)
    if not isinstance(value, list):
        return [ValidationMessage("ERROR", path, f"review packet JSON field must be a list: {label or field}")]
    return []


def _require_tests(path: Path, value: Any) -> list[ValidationMessage]:
    if not isinstance(value, list):
        return [ValidationMessage("ERROR", path, "review packet JSON field must be a list: tests")]
    messages: list[ValidationMessage] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            messages.append(ValidationMessage("ERROR", path, f"review packet JSON tests[{index}] must be an object"))
            continue
        for key in ("command", "result"):
            if not isinstance(item.get(key), str) or not item.get(key, "").strip():
                messages.append(ValidationMessage("ERROR", path, f"review packet JSON tests[{index}].{key} must be a non-empty string"))
    return messages


def _field_value(payload: Any, field: str) -> Any:
    current = payload
    for part in field.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current
