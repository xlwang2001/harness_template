"""SPEC-aligned orchestration policy for the hardened runtime."""

from __future__ import annotations

import time
import logging
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from threading import RLock
from typing import Any, Mapping, Protocol

from .agent import AgentRunnerError, CodexAgentRunner
from .models import Issue, RetryEntry, RunAttemptRecord, RunningEntry, RuntimeConfig, RuntimeState
from .prompt import render_prompt
from .runtime_logging import emit_runtime_log
from .tracker import IssueTrackerClient, TrackerError
from .workflow import ConfigValidationError, validate_dispatch_config
from .workspace import WorkspaceManager


def monotonic_ms() -> int:
    return int(time.monotonic() * 1000)


class Orchestrator:
    def __init__(
        self,
        config: RuntimeConfig,
        tracker: IssueTrackerClient,
        workspace_manager: WorkspaceManager,
        agent_runner: CodexAgentRunner,
        prompt_template: str,
        executor: "Submitter | None" = None,
        logger: logging.Logger | None = None,
    ):
        self.config = config
        self.tracker = tracker
        self.workspace_manager = workspace_manager
        self.agent_runner = agent_runner
        self.prompt_template = prompt_template
        self.executor = executor or ThreadPoolExecutor(max_workers=config.max_concurrent_agents)
        self.logger = logger or logging.getLogger("harness.runtime")
        self._lock = RLock()
        self.state = RuntimeState(
            poll_interval_ms=config.polling_interval_ms,
            max_concurrent_agents=config.max_concurrent_agents,
        )

    def apply_reload(self, config: RuntimeConfig, prompt_template: str) -> None:
        with self._lock:
            self.config = config
            self.prompt_template = prompt_template
            self.state.poll_interval_ms = config.polling_interval_ms
            self.state.max_concurrent_agents = config.max_concurrent_agents
            self.workspace_manager = WorkspaceManager(config)
            if hasattr(self.tracker, "config"):
                self.tracker.config = config
            if hasattr(self.agent_runner, "config"):
                self.agent_runner.config = config
            emit_runtime_log(
                self.logger,
                "config_applied",
                workflow=config.workflow_path,
                poll_interval_ms=config.polling_interval_ms,
                max_concurrent_agents=config.max_concurrent_agents,
                workspace_root=config.workspace_root,
                secrets=(config.tracker_api_key,),
            )

    def eligible(self, issue: Issue) -> bool:
        if not issue.id or not issue.identifier or not issue.title or not issue.state:
            return False
        if not self.config.is_active_state(issue.state) or self.config.is_terminal_state(issue.state):
            return False
        if issue.id in self.state.running or issue.id in self.state.claimed:
            return False
        if self.available_slots_for(issue.state) <= 0:
            return False
        if issue.normalized_state == "todo":
            for blocker in issue.blocked_by:
                if not self.config.is_terminal_state(blocker.state):
                    return False
        return True

    def available_slots_for(self, state: str) -> int:
        global_available = max(self.config.max_concurrent_agents - len(self.state.running), 0)
        state_key = state.lower()
        state_limit = self.config.max_concurrent_agents_by_state.get(state_key, self.config.max_concurrent_agents)
        running_in_state = sum(1 for entry in self.state.running.values() if entry.issue.normalized_state == state_key)
        return min(global_available, max(state_limit - running_in_state, 0))

    def sort_for_dispatch(self, issues: list[Issue]) -> list[Issue]:
        return sorted(
            issues,
            key=lambda issue: (
                issue.priority if issue.priority is not None else 999999,
                issue.created_at or datetime.max.replace(tzinfo=timezone.utc),
                issue.identifier,
            ),
        )

    def tick_once(self) -> None:
        emit_runtime_log(self.logger, "tick_started", running=len(self.state.running), retrying=len(self.state.retry_attempts), secrets=(self.config.tracker_api_key,))
        self.reconcile_running()
        try:
            validate_dispatch_config(self.config)
        except ConfigValidationError as exc:
            emit_runtime_log(self.logger, "dispatch_preflight_failed", level=logging.ERROR, error=exc, secrets=(self.config.tracker_api_key,))
            return
        self.process_due_retries()
        try:
            candidates = self.tracker.fetch_candidate_issues()
        except TrackerError as exc:
            emit_runtime_log(self.logger, "candidate_fetch_failed", level=logging.WARNING, error=exc, secrets=(self.config.tracker_api_key,))
            return
        for issue in self.sort_for_dispatch(candidates):
            if len(self.state.running) >= self.config.max_concurrent_agents:
                break
            if self.eligible(issue):
                self.dispatch_issue(issue, attempt=None)
        emit_runtime_log(self.logger, "tick_completed", running=len(self.state.running), retrying=len(self.state.retry_attempts), secrets=(self.config.tracker_api_key,))

    def dispatch_issue(self, issue: Issue, attempt: int | None) -> None:
        with self._lock:
            if not self.eligible(issue):
                emit_runtime_log(
                    self.logger,
                    "dispatch_skipped",
                    issue_id=issue.id,
                    issue_identifier=issue.identifier,
                    state=issue.state,
                    reason="not_eligible",
                    secrets=(self.config.tracker_api_key,),
                )
                return
            self.state.claimed.add(issue.id)
            self.state.running[issue.id] = RunningEntry(issue=issue, started_at=datetime.now(timezone.utc), attempt=attempt)
            emit_runtime_log(
                self.logger,
                "dispatch_started",
                issue_id=issue.id,
                issue_identifier=issue.identifier,
                state=issue.state,
                attempt=attempt,
                secrets=(self.config.tracker_api_key,),
            )
        future = self.executor.submit(self._run_issue, issue, attempt)
        with self._lock:
            if issue.id in self.state.running:
                self.state.worker_futures[issue.id] = future
        future.add_done_callback(lambda done, issue_id=issue.id: self._finish_future(issue_id, done))

    def _run_issue(self, issue: Issue, attempt: int | None) -> None:
        workspace = None
        try:
            workspace = self.workspace_manager.create_for_issue(issue.identifier)
            with self._lock:
                entry = self.state.running.get(issue.id)
                if entry is None:
                    return
                entry.workspace_path = workspace.path
            self.workspace_manager.run_hook("before_run", workspace, fatal=True)
            prompt = render_prompt(self.prompt_template, issue, attempt)
            emit_runtime_log(
                self.logger,
                "agent_session_started",
                issue_id=issue.id,
                issue_identifier=issue.identifier,
                workspace=workspace.path,
                attempt=attempt,
                secrets=(self.config.tracker_api_key,),
            )
            emitted_via_callback = False

            def on_event(event: dict[str, object]) -> None:
                nonlocal emitted_via_callback
                emitted_via_callback = True
                self.record_agent_event(issue.id, event)

            result = self.agent_runner.run_turn(issue, prompt, workspace.path, attempt, on_event=on_event)
            if not emitted_via_callback:
                for event in result.events:
                    self.record_agent_event(issue.id, event)
            emit_runtime_log(
                self.logger,
                "agent_session_completed",
                issue_id=issue.id,
                issue_identifier=issue.identifier,
                workspace=workspace.path,
                attempt=attempt,
                secrets=(self.config.tracker_api_key,),
            )
        except (AgentRunnerError, Exception) as exc:
            emit_runtime_log(
                self.logger,
                "agent_session_failed",
                level=logging.ERROR,
                issue_id=issue.id,
                issue_identifier=issue.identifier,
                attempt=attempt,
                error=exc,
                secrets=(self.config.tracker_api_key,),
            )
            raise RuntimeError(str(exc)) from exc
        finally:
            if workspace is not None:
                self.workspace_manager.run_hook("after_run", workspace, fatal=False)

    def _finish_future(self, issue_id: str, future: Future[None]) -> None:
        try:
            future.result()
        except Exception as exc:
            self.finish_issue(issue_id, normal=False, error=str(exc))
            return
        self.finish_issue(issue_id, normal=True, error=None)

    def finish_issue(self, issue_id: str, *, normal: bool, error: str | None) -> None:
        with self._lock:
            entry = self.state.running.pop(issue_id, None)
            if not entry:
                self.state.worker_futures.pop(issue_id, None)
                return
            self.state.worker_futures.pop(issue_id, None)
            if normal:
                self._record_attempt_locked(entry, status="succeeded", error=None)
                self.state.completed.add(issue_id)
                emit_runtime_log(
                    self.logger,
                    "worker_completed",
                    issue_id=issue_id,
                    issue_identifier=entry.issue.identifier,
                    secrets=(self.config.tracker_api_key,),
                )
                self.schedule_retry(entry.issue, attempt=1, error=None, continuation=True)
            else:
                self._record_attempt_locked(entry, status=self._attempt_status_for_error(error), error=error)
                emit_runtime_log(
                    self.logger,
                    "worker_failed",
                    level=logging.ERROR,
                    issue_id=issue_id,
                    issue_identifier=entry.issue.identifier,
                    error=error,
                    secrets=(self.config.tracker_api_key,),
                )
                self.schedule_retry(entry.issue, attempt=1, error=error, continuation=False)

    def record_agent_event(self, issue_id: str, event: Mapping[str, Any]) -> None:
        with self._lock:
            entry = self.state.running.get(issue_id)
            if entry is None:
                return
            event_name = _event_name(event)
            if event_name:
                entry.last_codex_event = event_name
                if event_name == "turn_completed":
                    entry.turn_count += 1
            entry.last_codex_timestamp = _event_timestamp(event)
            entry.last_codex_message = _event_message(event)
            entry.session_id = _string_or_none(event.get("session_id") or event.get("sessionId")) or entry.session_id
            entry.thread_id = _string_or_none(event.get("thread_id") or event.get("threadId")) or entry.thread_id
            entry.turn_id = _string_or_none(event.get("turn_id") or event.get("turnId")) or entry.turn_id
            entry.codex_app_server_pid = _string_or_none(event.get("codex_app_server_pid") or event.get("codexAppServerPid")) or entry.codex_app_server_pid
            usage = _absolute_token_usage(event)
            if usage:
                self._apply_token_usage_locked(entry, usage)
            rate_limits = _rate_limits(event)
            if rate_limits is not None:
                self.state.codex_rate_limits = rate_limits

    def _apply_token_usage_locked(self, entry: RunningEntry, usage: dict[str, int]) -> None:
        input_tokens = usage.get("input_tokens")
        output_tokens = usage.get("output_tokens")
        total_tokens = usage.get("total_tokens")
        if input_tokens is not None:
            self.state.codex_totals["input_tokens"] += max(input_tokens - entry.last_reported_input_tokens, 0)
            entry.last_reported_input_tokens = input_tokens
            entry.codex_input_tokens = input_tokens
        if output_tokens is not None:
            self.state.codex_totals["output_tokens"] += max(output_tokens - entry.last_reported_output_tokens, 0)
            entry.last_reported_output_tokens = output_tokens
            entry.codex_output_tokens = output_tokens
        if total_tokens is not None:
            self.state.codex_totals["total_tokens"] += max(total_tokens - entry.last_reported_total_tokens, 0)
            entry.last_reported_total_tokens = total_tokens
            entry.codex_total_tokens = total_tokens

    def _record_attempt_locked(self, entry: RunningEntry, *, status: str, error: str | None) -> None:
        self.state.last_attempts[entry.issue.id] = RunAttemptRecord(
            issue_id=entry.issue.id,
            identifier=entry.issue.identifier,
            attempt=entry.attempt,
            workspace_path=entry.workspace_path,
            started_at=entry.started_at,
            finished_at=datetime.now(timezone.utc),
            status=status,
            error=error,
        )

    @staticmethod
    def _attempt_status_for_error(error: str | None) -> str:
        if error == "turn_timeout":
            return "timed_out"
        if error == "stalled":
            return "stalled"
        return "failed"

    def schedule_retry(self, issue: Issue, *, attempt: int, error: str | None, continuation: bool = False) -> None:
        delay = 1000 if continuation else min(10000 * (2 ** max(attempt - 1, 0)), self.config.max_retry_backoff_ms)
        self.state.retry_attempts[issue.id] = RetryEntry(
            issue_id=issue.id,
            identifier=issue.identifier,
            attempt=attempt,
            due_at_ms=monotonic_ms() + delay,
            error=error,
        )
        emit_runtime_log(
            self.logger,
            "retry_scheduled",
            issue_id=issue.id,
            issue_identifier=issue.identifier,
            attempt=attempt,
            due_at_ms=self.state.retry_attempts[issue.id].due_at_ms,
            error=error,
            continuation=continuation,
            secrets=(self.config.tracker_api_key,),
        )

    def retry_due(self, issue_id: str) -> None:
        retry = self.state.retry_attempts.pop(issue_id, None)
        if not retry:
            return
        emit_runtime_log(
            self.logger,
            "retry_due",
            issue_id=issue_id,
            issue_identifier=retry.identifier,
            attempt=retry.attempt,
            secrets=(self.config.tracker_api_key,),
        )
        try:
            candidates = self.tracker.fetch_candidate_issues()
        except TrackerError:
            issue = Issue(id=retry.issue_id, identifier=retry.identifier, title=retry.identifier, state="unknown")
            self.schedule_retry(issue, attempt=retry.attempt + 1, error="retry poll failed")
            return
        issue = next((candidate for candidate in candidates if candidate.id == issue_id), None)
        if issue is None:
            self.state.claimed.discard(issue_id)
            emit_runtime_log(
                self.logger,
                "retry_released",
                issue_id=issue_id,
                issue_identifier=retry.identifier,
                reason="not_candidate",
                secrets=(self.config.tracker_api_key,),
            )
            return
        self.state.claimed.discard(issue_id)
        if self.eligible(issue):
            self.dispatch_issue(issue, attempt=retry.attempt)
        else:
            self.schedule_retry(issue, attempt=retry.attempt + 1, error="no available orchestrator slots")

    def process_due_retries(self) -> None:
        now = monotonic_ms()
        due = [issue_id for issue_id, retry in self.state.retry_attempts.items() if retry.due_at_ms <= now]
        for issue_id in due:
            self.retry_due(issue_id)

    def reconcile_running(self) -> None:
        self.reconcile_stalled()
        if not self.state.running:
            return
        emit_runtime_log(self.logger, "reconciliation_started", running=len(self.state.running), secrets=(self.config.tracker_api_key,))
        try:
            refreshed = self.tracker.fetch_issue_states_by_ids(list(self.state.running))
        except TrackerError as exc:
            emit_runtime_log(self.logger, "reconciliation_failed", level=logging.WARNING, error=exc, secrets=(self.config.tracker_api_key,))
            return
        for issue in refreshed:
            if issue.id not in self.state.running:
                continue
            if self.config.is_terminal_state(issue.state):
                self.stop_running_issue(issue, cleanup=True)
            elif self.config.is_active_state(issue.state):
                self.state.running[issue.id].issue = issue
            else:
                self.stop_running_issue(issue, cleanup=False)
        emit_runtime_log(self.logger, "reconciliation_completed", running=len(self.state.running), secrets=(self.config.tracker_api_key,))

    def stop_running_issue(self, issue: Issue, *, cleanup: bool) -> None:
        with self._lock:
            entry = self.state.running.pop(issue.id, None)
            future = self.state.worker_futures.pop(issue.id, None)
            self.state.claimed.discard(issue.id)
            if entry:
                self._record_attempt_locked(entry, status="canceled_by_reconciliation", error=None)
        if not entry:
            return
        cancel_requested = future.cancel() if future and not future.done() else False
        if cleanup:
            self.workspace_manager.cleanup_for_issue(issue.identifier)
        emit_runtime_log(
            self.logger,
            "reconciliation_stopped",
            issue_id=issue.id,
            issue_identifier=issue.identifier,
            state=issue.state,
            cleanup=cleanup,
            cancel_requested=cancel_requested,
            secrets=(self.config.tracker_api_key,),
        )

    def shutdown(self, reason: str) -> None:
        with self._lock:
            futures = list(self.state.worker_futures.values())
            running_count = len(self.state.running)
            self.state.running.clear()
            self.state.worker_futures.clear()
            self.state.claimed.clear()
        cancelled = 0
        for future in futures:
            if future.done():
                continue
            if future.cancel():
                cancelled += 1
        executor_shutdown = getattr(self.executor, "shutdown", None)
        if callable(executor_shutdown):
            try:
                executor_shutdown(wait=False, cancel_futures=True)
            except TypeError:
                executor_shutdown(wait=False)
        emit_runtime_log(
            self.logger,
            "orchestrator_shutdown_completed",
            reason=reason,
            running=running_count,
            cancelled=cancelled,
            secrets=(self.config.tracker_api_key,),
        )

    def reconcile_stalled(self) -> None:
        if self.config.codex_stall_timeout_ms <= 0:
            return
        now = datetime.now(timezone.utc)
        for issue_id, entry in list(self.state.running.items()):
            marker = entry.last_codex_timestamp or entry.started_at
            elapsed_ms = int((now - marker).total_seconds() * 1000)
            if elapsed_ms > self.config.codex_stall_timeout_ms:
                emit_runtime_log(self.logger, "session_stalled", issue_id=issue_id, issue_identifier=entry.issue.identifier, elapsed_ms=elapsed_ms, secrets=(self.config.tracker_api_key,))
                self.finish_issue(issue_id, normal=False, error="stalled")

    def startup_terminal_cleanup(self) -> None:
        try:
            terminal_issues = self.tracker.fetch_issues_by_states(list(self.config.terminal_states))
        except TrackerError as exc:
            emit_runtime_log(self.logger, "startup_cleanup_failed", level=logging.WARNING, error=exc, secrets=(self.config.tracker_api_key,))
            return
        for issue in terminal_issues:
            self.workspace_manager.cleanup_for_issue(issue.identifier)
        emit_runtime_log(self.logger, "startup_cleanup_completed", cleaned=len(terminal_issues), secrets=(self.config.tracker_api_key,))

    def snapshot(self) -> dict[str, object]:
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "counts": {"running": len(self.state.running), "retrying": len(self.state.retry_attempts)},
            "running": [
                {
                    "issue_id": entry.issue.id,
                    "issue_identifier": entry.issue.identifier,
                    "state": entry.issue.state,
                    "workspace_path": str(entry.workspace_path) if entry.workspace_path else None,
                    "session_id": entry.session_id,
                    "thread_id": entry.thread_id,
                    "turn_id": entry.turn_id,
                    "codex_app_server_pid": entry.codex_app_server_pid,
                    "turn_count": entry.turn_count,
                    "last_event": entry.last_codex_event,
                    "last_codex_event": entry.last_codex_event,
                    "last_codex_timestamp": entry.last_codex_timestamp.isoformat() if entry.last_codex_timestamp else None,
                    "last_message": entry.last_codex_message,
                    "last_codex_message": entry.last_codex_message,
                    "codex_input_tokens": entry.codex_input_tokens,
                    "codex_output_tokens": entry.codex_output_tokens,
                    "codex_total_tokens": entry.codex_total_tokens,
                    "last_reported_input_tokens": entry.last_reported_input_tokens,
                    "last_reported_output_tokens": entry.last_reported_output_tokens,
                    "last_reported_total_tokens": entry.last_reported_total_tokens,
                    "started_at": entry.started_at.isoformat(),
                }
                for entry in self.state.running.values()
            ],
            "retrying": [retry.__dict__ for retry in self.state.retry_attempts.values()],
            "codex_totals": self.state.codex_totals,
            "rate_limits": self.state.codex_rate_limits,
        }

    def issue_detail(self, identifier: str) -> dict[str, object] | None:
        wanted = identifier.lower()
        for entry in self.state.running.values():
            if entry.issue.identifier.lower() == wanted:
                retry = self.state.retry_attempts.get(entry.issue.id)
                attempt = self.state.last_attempts.get(entry.issue.id)
                return {
                    "issue_identifier": entry.issue.identifier,
                    "issue_id": entry.issue.id,
                    "status": "running",
                    "workspace": {"path": str(entry.workspace_path) if entry.workspace_path else None},
                    "attempts": {"current_retry_attempt": retry.attempt if retry else None},
                    "running": self._running_detail(entry),
                    "retry": retry.__dict__ if retry else None,
                    "last_attempt": self._attempt_detail(attempt),
                    "tracked": {},
                }
        for retry in self.state.retry_attempts.values():
            if retry.identifier.lower() == wanted:
                attempt = self.state.last_attempts.get(retry.issue_id)
                return {
                    "issue_identifier": retry.identifier,
                    "issue_id": retry.issue_id,
                    "status": "retrying",
                    "workspace": {"path": None},
                    "attempts": {"current_retry_attempt": retry.attempt},
                    "running": None,
                    "retry": retry.__dict__,
                    "last_attempt": self._attempt_detail(attempt),
                    "tracked": {},
                }
        for attempt in self.state.last_attempts.values():
            if attempt.identifier.lower() == wanted:
                return {
                    "issue_identifier": attempt.identifier,
                    "issue_id": attempt.issue_id,
                    "status": attempt.status,
                    "workspace": {"path": str(attempt.workspace_path) if attempt.workspace_path else None},
                    "attempts": {"current_retry_attempt": None},
                    "running": None,
                    "retry": None,
                    "last_attempt": self._attempt_detail(attempt),
                    "tracked": {},
                }
        return None

    def _running_detail(self, entry: RunningEntry) -> dict[str, object]:
        return {
            "session_id": entry.session_id,
            "turn_count": entry.turn_count,
            "state": entry.issue.state,
            "started_at": entry.started_at.isoformat(),
            "last_event": entry.last_codex_event,
            "last_message": entry.last_codex_message,
            "last_event_at": entry.last_codex_timestamp.isoformat() if entry.last_codex_timestamp else None,
            "tokens": {
                "input_tokens": entry.codex_input_tokens,
                "output_tokens": entry.codex_output_tokens,
                "total_tokens": entry.codex_total_tokens,
            },
        }

    def _attempt_detail(self, attempt: RunAttemptRecord | None) -> dict[str, object] | None:
        if attempt is None:
            return None
        return {
            "issue_id": attempt.issue_id,
            "identifier": attempt.identifier,
            "attempt": attempt.attempt,
            "workspace_path": str(attempt.workspace_path) if attempt.workspace_path else None,
            "started_at": attempt.started_at.isoformat(),
            "finished_at": attempt.finished_at.isoformat(),
            "status": attempt.status,
            "error": attempt.error,
        }


class Submitter(Protocol):
    def submit(self, fn, /, *args, **kwargs) -> Future:
        ...


def _event_name(event: Mapping[str, Any]) -> str | None:
    return _string_or_none(event.get("event") or event.get("type"))


def _event_timestamp(event: Mapping[str, Any]) -> datetime:
    raw = event.get("timestamp") or event.get("time") or event.get("created_at")
    if isinstance(raw, datetime):
        return raw
    if raw:
        try:
            return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _event_message(event: Mapping[str, Any]) -> str | None:
    value = event.get("message") or event.get("summary") or event.get("text")
    if value is None and isinstance(event.get("payload"), str):
        value = event["payload"]
    if value is None:
        return None
    text = str(value)
    return text if len(text) <= 500 else f"{text[:497]}..."


def _absolute_token_usage(event: Mapping[str, Any]) -> dict[str, int] | None:
    event_name = _event_name(event)
    payload = event.get("payload")
    payload_map = payload if isinstance(payload, Mapping) else {}
    candidates: list[Any] = []
    if event_name == "thread/tokenUsage/updated":
        candidates.extend([event.get("usage"), payload_map.get("usage"), payload, event])
    candidates.extend(
        [
            event.get("total_token_usage"),
            event.get("totalTokenUsage"),
            payload_map.get("total_token_usage"),
            payload_map.get("totalTokenUsage"),
        ]
    )
    for candidate in candidates:
        if isinstance(candidate, Mapping):
            usage = _normalize_token_usage(candidate)
            if usage:
                return usage
    return None


def _normalize_token_usage(value: Mapping[str, Any]) -> dict[str, int] | None:
    input_tokens = _first_int(value, ("input_tokens", "inputTokens", "prompt_tokens", "promptTokens"))
    output_tokens = _first_int(value, ("output_tokens", "outputTokens", "completion_tokens", "completionTokens"))
    total_tokens = _first_int(value, ("total_tokens", "totalTokens", "total"))
    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens
    usage = {
        key: token
        for key, token in (
            ("input_tokens", input_tokens),
            ("output_tokens", output_tokens),
            ("total_tokens", total_tokens),
        )
        if token is not None
    }
    return usage or None


def _rate_limits(event: Mapping[str, Any]) -> Any:
    payload = event.get("payload")
    payload_map = payload if isinstance(payload, Mapping) else {}
    for key in ("rate_limits", "rateLimits", "rate_limit", "rateLimit"):
        if key in event:
            return event[key]
        if key in payload_map:
            return payload_map[key]
    return None


def _first_int(value: Mapping[str, Any], keys: tuple[str, ...]) -> int | None:
    for key in keys:
        token = _coerce_int(value.get(key))
        if token is not None:
            return token
    return None


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        token = int(value)
    except (TypeError, ValueError):
        return None
    return max(token, 0)


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
