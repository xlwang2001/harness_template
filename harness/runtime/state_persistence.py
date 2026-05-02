"""Optional durable runtime state persistence."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import RetryEntry, RunAttemptRecord, RuntimeState
from .runtime_logging import emit_runtime_log


STATE_VERSION = 1


class RuntimeStateStore:
    def __init__(self, path: Path, logger: logging.Logger | None = None):
        self.path = path
        self.logger = logger or logging.getLogger("harness.runtime")

    def load_into(self, state: RuntimeState, *, persist_retries: bool, persist_sessions: bool) -> None:
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("runtime state payload must be an object")
            if persist_retries:
                state.retry_attempts = _load_retries(payload.get("retry_attempts"))
            state.last_attempts = _load_attempts(payload.get("last_attempts"))
            state.completed = {str(item) for item in payload.get("completed", []) if item is not None}
            state.codex_totals.update(_load_codex_totals(payload.get("codex_totals")))
            rate_limits = payload.get("codex_rate_limits")
            state.codex_rate_limits = rate_limits if isinstance(rate_limits, dict) else None
            if persist_sessions:
                state.session_metadata = _load_session_metadata(payload.get("session_metadata"))
        except Exception as exc:
            emit_runtime_log(self.logger, "runtime_state_load_failed", level=logging.WARNING, path=self.path, error=exc)

    def save(self, state: RuntimeState, *, persist_retries: bool, persist_sessions: bool) -> None:
        payload = {
            "version": STATE_VERSION,
            "retry_attempts": _dump_retries(state.retry_attempts) if persist_retries else {},
            "last_attempts": _dump_attempts(state.last_attempts),
            "completed": sorted(state.completed),
            "codex_totals": dict(state.codex_totals),
            "codex_rate_limits": state.codex_rate_limits,
            "session_metadata": _safe_session_metadata(state.session_metadata) if persist_sessions else {},
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, temp_name = tempfile.mkstemp(prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle, sort_keys=True)
                    handle.write("\n")
                os.replace(temp_name, self.path)
            finally:
                if os.path.exists(temp_name):
                    os.unlink(temp_name)
        except Exception as exc:
            emit_runtime_log(self.logger, "runtime_state_save_failed", level=logging.WARNING, path=self.path, error=exc)


def _dump_retries(retries: dict[str, RetryEntry]) -> dict[str, dict[str, Any]]:
    return {issue_id: dict(entry.__dict__) for issue_id, entry in retries.items()}


def _load_retries(raw: Any) -> dict[str, RetryEntry]:
    if not isinstance(raw, dict):
        return {}
    retries: dict[str, RetryEntry] = {}
    for issue_id, value in raw.items():
        if not isinstance(value, dict):
            continue
        try:
            retries[str(issue_id)] = RetryEntry(
                issue_id=str(value["issue_id"]),
                identifier=str(value["identifier"]),
                attempt=int(value["attempt"]),
                due_at_ms=int(value["due_at_ms"]),
                error=value.get("error"),
            )
        except (KeyError, TypeError, ValueError):
            continue
    return retries


def _dump_attempts(attempts: dict[str, RunAttemptRecord]) -> dict[str, dict[str, Any]]:
    return {
        issue_id: {
            "issue_id": attempt.issue_id,
            "identifier": attempt.identifier,
            "attempt": attempt.attempt,
            "workspace_path": str(attempt.workspace_path) if attempt.workspace_path else None,
            "started_at": attempt.started_at.isoformat(),
            "finished_at": attempt.finished_at.isoformat(),
            "status": attempt.status,
            "error": attempt.error,
        }
        for issue_id, attempt in attempts.items()
    }


def _load_attempts(raw: Any) -> dict[str, RunAttemptRecord]:
    if not isinstance(raw, dict):
        return {}
    attempts: dict[str, RunAttemptRecord] = {}
    for issue_id, value in raw.items():
        if not isinstance(value, dict):
            continue
        try:
            attempts[str(issue_id)] = RunAttemptRecord(
                issue_id=str(value["issue_id"]),
                identifier=str(value["identifier"]),
                attempt=value.get("attempt"),
                workspace_path=Path(value["workspace_path"]) if value.get("workspace_path") else None,
                started_at=datetime.fromisoformat(str(value["started_at"])),
                finished_at=datetime.fromisoformat(str(value["finished_at"])),
                status=str(value["status"]),
                error=value.get("error"),
            )
        except (KeyError, TypeError, ValueError):
            continue
    return attempts


def _load_codex_totals(raw: Any) -> dict[str, float]:
    if not isinstance(raw, dict):
        return {}
    totals: dict[str, float] = {}
    for key in ("input_tokens", "output_tokens", "total_tokens", "seconds_running"):
        try:
            totals[key] = float(raw[key])
        except (KeyError, TypeError, ValueError):
            continue
    return totals


def _load_session_metadata(raw: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(raw, dict):
        return {}
    return {str(issue_id): _safe_session_payload(value) for issue_id, value in raw.items() if isinstance(value, dict)}


def _safe_session_metadata(metadata: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {issue_id: _safe_session_payload(value) for issue_id, value in metadata.items()}


def _safe_session_payload(value: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "issue_identifier",
        "session_id",
        "thread_id",
        "turn_id",
        "turn_count",
        "last_codex_event",
        "last_codex_timestamp",
        "last_codex_message",
        "codex_input_tokens",
        "codex_output_tokens",
        "codex_total_tokens",
    }
    return {key: value for key, value in value.items() if key in allowed}
