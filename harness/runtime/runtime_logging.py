"""Structured runtime logging with conservative secret redaction."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Iterable, Mapping, Any


SENSITIVE_KEY_PARTS = ("api_key", "token", "secret", "authorization", "password")
REDACTED = "[REDACTED]"
OWNED_HANDLER_ATTR = "_harness_runtime_owned"

logging.getLogger("harness.runtime").addHandler(logging.NullHandler())


def configure_runtime_logging(
    logger: logging.Logger,
    *,
    level: str = "INFO",
    console: bool = True,
    file_path: Path | None = None,
    secrets: Iterable[str | None] = (),
) -> None:
    """Configure harness-owned runtime log handlers without touching external handlers."""

    for handler in list(logger.handlers):
        if getattr(handler, OWNED_HANDLER_ATTR, False):
            logger.removeHandler(handler)
            handler.close()
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.propagate = False
    formatter = logging.Formatter("%(asctime)s level=%(levelname)s %(message)s")
    if console:
        handler = logging.StreamHandler(sys.stderr)
        setattr(handler, OWNED_HANDLER_ATTR, True)
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    if file_path is not None:
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            handler = logging.FileHandler(file_path, encoding="utf-8")
        except OSError as exc:
            emit_runtime_log(logger, "log_sink_failed", level=logging.WARNING, path=file_path, error=exc, secrets=secrets)
        else:
            setattr(handler, OWNED_HANDLER_ATTR, True)
            handler.setFormatter(formatter)
            logger.addHandler(handler)


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
