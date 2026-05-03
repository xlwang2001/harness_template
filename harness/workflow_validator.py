"""Validate Symphony WORKFLOW.md files."""

from __future__ import annotations

import re
from pathlib import Path

from .validation import ValidationMessage, missing_file, read_text


REQUIRED_TOP_LEVEL_KEYS = ("tracker", "workspace", "agent", "codex")
UNSUPPORTED_YAML_FEATURES = (
    (re.compile(r"(^|[:\s\[,])&[A-Za-z0-9_-]+"), "YAML anchors are outside the supported WORKFLOW.md subset"),
    (re.compile(r"(^|[:\s\[,])\*[A-Za-z0-9_-]+"), "YAML aliases are outside the supported WORKFLOW.md subset"),
    (re.compile(r"^\s*<<\s*:", flags=re.MULTILINE), "YAML merge keys are outside the supported WORKFLOW.md subset"),
    (re.compile(r"(^|[:\s\[,])![A-Za-z][A-Za-z0-9_/.-]*"), "YAML custom tags are outside the supported WORKFLOW.md subset"),
    (re.compile(r":\s*>[+-]?\s*(?:#.*)?$", flags=re.MULTILINE), "YAML folded block scalars are outside the supported WORKFLOW.md subset; use | block scalars"),
)


def validate_workflow(root: Path) -> list[ValidationMessage]:
    missing = missing_file(root, "WORKFLOW.md")
    if missing:
        return [missing]

    path = root / "WORKFLOW.md"
    text = read_text(path)
    messages: list[ValidationMessage] = []
    front_matter, body = _split_front_matter(text)
    if front_matter is None:
        return [ValidationMessage("ERROR", path, "WORKFLOW.md must start with YAML-style front matter delimited by ---")]

    messages.extend(_warn_unsupported_yaml_features(path, front_matter))

    for key in REQUIRED_TOP_LEVEL_KEYS:
        if not re.search(rf"^{re.escape(key)}:\s*$", front_matter, flags=re.MULTILINE):
            messages.append(ValidationMessage("ERROR", path, f"front matter missing required section: {key}"))

    if "{{ issue.identifier }}" not in body:
        messages.append(ValidationMessage("ERROR", path, "prompt body should include {{ issue.identifier }}"))
    if "{{ issue.title }}" not in body:
        messages.append(ValidationMessage("ERROR", path, "prompt body should include {{ issue.title }}"))
    if "{{ issue.description }}" not in body:
        messages.append(ValidationMessage("ERROR", path, "prompt body should include {{ issue.description }}"))

    if "active_states:" not in front_matter:
        messages.append(ValidationMessage("ERROR", path, "tracker config should define active_states"))
    if "terminal_states:" not in front_matter:
        messages.append(ValidationMessage("ERROR", path, "tracker config should define terminal_states"))
    return messages


def _warn_unsupported_yaml_features(path: Path, front_matter: str) -> list[ValidationMessage]:
    messages: list[ValidationMessage] = []
    for pattern, message in UNSUPPORTED_YAML_FEATURES:
        if pattern.search(front_matter):
            messages.append(ValidationMessage("WARNING", path, message))
    return messages


def _split_front_matter(text: str) -> tuple[str | None, str]:
    if not text.startswith("---\n"):
        return None, text
    end = text.find("\n---", 4)
    if end == -1:
        return None, text
    front_matter = text[4:end]
    body = text[end + 4 :]
    return front_matter, body
