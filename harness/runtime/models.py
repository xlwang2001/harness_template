"""Domain models for the hardened Symphony runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class BlockerRef:
    id: str | None = None
    identifier: str | None = None
    state: str | None = None


@dataclass(frozen=True)
class Issue:
    id: str
    identifier: str
    title: str
    description: str | None = None
    priority: int | None = None
    state: str = ""
    branch_name: str | None = None
    url: str | None = None
    labels: tuple[str, ...] = ()
    blocked_by: tuple[BlockerRef, ...] = ()
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "Issue":
        labels = tuple(str(label).lower() for label in data.get("labels", ()) if label is not None)
        blockers = tuple(
            blocker if isinstance(blocker, BlockerRef) else BlockerRef(**blocker)
            for blocker in data.get("blocked_by", ())
        )
        return cls(
            id=str(data["id"]),
            identifier=str(data["identifier"]),
            title=str(data["title"]),
            description=data.get("description"),
            priority=_coerce_priority(data.get("priority")),
            state=str(data.get("state", "")),
            branch_name=data.get("branch_name"),
            url=data.get("url"),
            labels=labels,
            blocked_by=blockers,
            created_at=_parse_datetime(data.get("created_at")),
            updated_at=_parse_datetime(data.get("updated_at")),
        )

    @property
    def normalized_state(self) -> str:
        return self.state.lower()


@dataclass(frozen=True)
class WorkflowDefinition:
    path: Path
    config: dict[str, Any]
    prompt_template: str
    loaded_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True)
class RuntimeConfig:
    workflow_path: Path
    tracker_kind: str
    tracker_endpoint: str
    tracker_api_key: str | None
    tracker_project_slug: str | None
    active_states: tuple[str, ...]
    terminal_states: tuple[str, ...]
    polling_interval_ms: int
    workspace_root: Path
    hooks: dict[str, str | None]
    hooks_timeout_ms: int
    max_concurrent_agents: int
    max_turns: int
    max_retry_backoff_ms: int
    max_concurrent_agents_by_state: dict[str, int]
    codex_command: str
    codex_turn_timeout_ms: int
    codex_read_timeout_ms: int
    codex_stall_timeout_ms: int
    approval_policy: str
    thread_sandbox: str
    turn_sandbox_policy: str

    def is_active_state(self, state: str | None) -> bool:
        return (state or "").lower() in {item.lower() for item in self.active_states}

    def is_terminal_state(self, state: str | None) -> bool:
        return (state or "").lower() in {item.lower() for item in self.terminal_states}


@dataclass(frozen=True)
class Workspace:
    path: Path
    workspace_key: str
    created_now: bool


@dataclass
class RunningEntry:
    issue: Issue
    started_at: datetime
    workspace_path: Path | None = None
    session_id: str | None = None
    thread_id: str | None = None
    turn_id: str | None = None
    codex_app_server_pid: str | None = None
    last_codex_event: str | None = None
    last_codex_timestamp: datetime | None = None
    last_codex_message: str | None = None
    codex_input_tokens: int = 0
    codex_output_tokens: int = 0
    codex_total_tokens: int = 0
    last_reported_input_tokens: int = 0
    last_reported_output_tokens: int = 0
    last_reported_total_tokens: int = 0
    turn_count: int = 0


@dataclass
class RetryEntry:
    issue_id: str
    identifier: str
    attempt: int
    due_at_ms: int
    error: str | None = None


@dataclass
class RuntimeState:
    poll_interval_ms: int
    max_concurrent_agents: int
    running: dict[str, RunningEntry] = field(default_factory=dict)
    worker_futures: dict[str, Any] = field(default_factory=dict)
    claimed: set[str] = field(default_factory=set)
    retry_attempts: dict[str, RetryEntry] = field(default_factory=dict)
    completed: set[str] = field(default_factory=set)
    codex_totals: dict[str, float] = field(
        default_factory=lambda: {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "seconds_running": 0.0,
        }
    )
    codex_rate_limits: dict[str, Any] | None = None


def _coerce_priority(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
