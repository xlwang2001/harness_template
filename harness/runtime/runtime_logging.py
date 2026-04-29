"""Structured runtime logging with conservative secret redaction."""

from __future__ import annotations

import logging
from typing import Iterable, Mapping, Any


SENSITIVE_KEY_PARTS = ("api_key", "token", "secret", "authorization", "password")
REDACTED = "[REDACTED]"

logging.getLogger("harness.runtime").addHandler(logging.NullHandler())


def emit_runtime_log(
    logger: logging.Logger,
    event: str,
    *,
    level: int = logging.INFO,
    secrets: Iterable[str | None] = (),
    **fields: Any,
) -> None:
    """Emit a stable key=value runtime log line."""

    secret_values = tuple(str(secret) for secret in secrets if secret)
    rendered = [f"event={event}"]
    for key in sorted(fields):
        rendered.append(f"{key}={_redact_field(key, fields[key], secret_values)}")
    logger.log(level, " ".join(rendered))


def redact_mapping(mapping: Mapping[str, Any], *, secrets: Iterable[str | None] = ()) -> dict[str, str]:
    secret_values = tuple(str(secret) for secret in secrets if secret)
    return {key: _redact_field(key, value, secret_values) for key, value in mapping.items()}


def _redact_field(key: str, value: Any, secrets: tuple[str, ...]) -> str:
    text = str(value)
    lowered = key.lower()
    if any(part in lowered for part in SENSITIVE_KEY_PARTS):
        return REDACTED
    for secret in secrets:
        if secret and secret in text:
            text = text.replace(secret, REDACTED)
    return text
