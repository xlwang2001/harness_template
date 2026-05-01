"""Strict prompt rendering for workflow templates."""

from __future__ import annotations

import dataclasses
import re
from typing import Any

from .models import Issue


class TemplateRenderError(ValueError):
    code = "template_render_error"


TAG_RE = re.compile(r"{{(.*?)}}", re.DOTALL)
VARIABLE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")


def render_prompt(template: str, issue: Issue, attempt: int | None = None) -> str:
    context = {"issue": dataclasses.asdict(issue), "attempt": attempt}
    _validate_template_tags(template)

    def replace(match: re.Match[str]) -> str:
        name = match.group(1).strip()
        if not VARIABLE_RE.fullmatch(name):
            raise TemplateRenderError(f"unsupported template expression: {name}")
        value = _resolve(context, name)
        return "" if value is None else str(value)

    return TAG_RE.sub(replace, template).strip()


def _validate_template_tags(template: str) -> None:
    index = 0
    while index < len(template):
        open_at = template.find("{{", index)
        close_at = template.find("}}", index)
        if close_at != -1 and (open_at == -1 or close_at < open_at):
            raise TemplateRenderError("malformed template interpolation")
        if open_at == -1:
            break
        close_at = template.find("}}", open_at + 2)
        if close_at == -1:
            raise TemplateRenderError("malformed template interpolation")
        index = close_at + 2
    for match in TAG_RE.finditer(template):
        expression = match.group(1).strip()
        if not expression:
            raise TemplateRenderError("empty template interpolation")
        if not VARIABLE_RE.fullmatch(expression):
            raise TemplateRenderError(f"unsupported template expression: {expression}")


def _resolve(context: dict[str, Any], dotted: str) -> Any:
    value: Any = context
    for part in dotted.split("."):
        if isinstance(value, dict) and part in value:
            value = value[part]
            continue
        raise TemplateRenderError(f"unknown template variable: {dotted}")
    return value
