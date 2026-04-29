"""Strict prompt rendering for workflow templates."""

from __future__ import annotations

import dataclasses
import re
from typing import Any

from .models import Issue


class TemplateRenderError(ValueError):
    code = "template_render_error"


TOKEN_RE = re.compile(r"{{\s*([A-Za-z_][A-Za-z0-9_.]*)\s*}}")


def render_prompt(template: str, issue: Issue, attempt: int | None = None) -> str:
    context = {"issue": dataclasses.asdict(issue), "attempt": attempt}

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        value = _resolve(context, name)
        return "" if value is None else str(value)

    return TOKEN_RE.sub(replace, template).strip()


def _resolve(context: dict[str, Any], dotted: str) -> Any:
    value: Any = context
    for part in dotted.split("."):
        if isinstance(value, dict) and part in value:
            value = value[part]
            continue
        raise TemplateRenderError(f"unknown template variable: {dotted}")
    return value
