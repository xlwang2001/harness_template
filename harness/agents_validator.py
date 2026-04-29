"""Validate AGENTS.md stays useful and compact."""

from __future__ import annotations

from pathlib import Path

from .validation import ValidationMessage, missing_file, read_text


def validate_agents(root: Path) -> list[ValidationMessage]:
    messages: list[ValidationMessage] = []
    missing = missing_file(root, "AGENTS.md")
    if missing:
        return [missing]

    path = root / "AGENTS.md"
    text = read_text(path)
    words = text.split()
    if len(words) > 500:
        messages.append(ValidationMessage("ERROR", path, "keep AGENTS.md under 500 words; link to docs instead"))
    if "docs/README.md" not in text:
        messages.append(ValidationMessage("ERROR", path, "AGENTS.md should link to docs/README.md"))
    if "WORKFLOW.md" not in text:
        messages.append(ValidationMessage("WARN", path, "AGENTS.md should mention WORKFLOW.md"))
    return messages
