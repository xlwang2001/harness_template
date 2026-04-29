"""Validate target repository documentation contract."""

from __future__ import annotations

import re
from pathlib import Path

from .validation import ValidationMessage, missing_file, read_text


REQUIRED_FILES = (
    "AGENTS.md",
    "WORKFLOW.md",
    "ARCHITECTURE.md",
    "docs/README.md",
    "docs/PRODUCT.md",
    "docs/ENGINEERING.md",
    "docs/QUALITY.md",
    "docs/RELIABILITY.md",
    "docs/SECURITY.md",
    "docs/OPERATING_MODEL.md",
    "docs/runbooks/local-dev.md",
    "docs/runbooks/ci-debugging.md",
    "docs/runbooks/release.md",
)

PLACEHOLDER_PATTERNS = (
    "TODO fill this in",
    "TBD",
    "{{",
    "}}",
)

LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def validate_docs(root: Path) -> list[ValidationMessage]:
    messages: list[ValidationMessage] = []
    for relative in REQUIRED_FILES:
        missing = missing_file(root, relative)
        if missing:
            messages.append(missing)

    docs_readme = root / "docs" / "README.md"
    if docs_readme.is_file():
        messages.extend(_validate_links(root / "docs", docs_readme))

    for path in sorted((root / "docs").rglob("*.md")) if (root / "docs").exists() else []:
        text = read_text(path)
        for marker in PLACEHOLDER_PATTERNS:
            if marker in text:
                messages.append(ValidationMessage("WARN", path, f"placeholder marker remains: {marker}"))
    return messages


def _validate_links(base: Path, path: Path) -> list[ValidationMessage]:
    messages: list[ValidationMessage] = []
    text = read_text(path)
    for match in LINK_RE.finditer(text):
        href = match.group(1)
        if href.startswith(("http://", "https://", "mailto:", "#")):
            continue
        link_path = href.split("#", 1)[0]
        if not link_path:
            continue
        candidate = (base / link_path).resolve()
        if not candidate.exists():
            messages.append(ValidationMessage("ERROR", path, f"link target does not exist: {href}"))
    return messages
