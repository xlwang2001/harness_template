"""SPEC-aligned orchestration policy for the hardened runtime."""

from __future__ import annotations

import time
from datetime import datetime, timezone

from .agent import AgentRunnerError, CodexAgentRunner
from .models import Issue, RetryEntry, RunningEntry, RuntimeConfig, RuntimeState
from .prompt import render_prompt
from .tracker import IssueTrackerClient, TrackerError
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
    ):
        self.config = config
        self.tracker = tracker
        self.workspace_manager = workspace_manager
        self.agent_runner = agent_runner
        self.prompt_template = prompt_template
        self.state = RuntimeState(
            poll_interval_ms=config.polling_interval_ms,
            max_concurrent_agents=config.max_concurrent_agents,
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
        self.reconcile_running()
        try:
            candidates = self.tracker.fetch_candidate_issues()
        except TrackerError:
            return
        for issue in self.sort_for_dispatch(candidates):
            if len(self.state.running) >= self.config.max_concurrent_agents:
                break
            if self.eligible(issue):
                self.dispatch_issue(issue, attempt=None)

    def dispatch_issue(self, issue: Issue, attempt: int | None) -> None:
        self.state.claimed.add(issue.id)
        self.state.running[issue.id] = RunningEntry(issue=issue, started_at=datetime.now(timezone.utc))
        try:
            workspace = self.workspace_manager.create_for_issue(issue.identifier)
            self.state.running[issue.id].workspace_path = workspace.path
            self.workspace_manager.run_hook("before_run", workspace, fatal=True)
            prompt = render_prompt(self.prompt_template, issue, attempt)
            self.agent_runner.run_turn(issue, prompt, workspace.path, attempt)
            self.workspace_manager.run_hook("after_run", workspace, fatal=False)
        except (AgentRunnerError, Exception) as exc:
            self.finish_issue(issue.id, normal=False, error=str(exc))
            return
        self.finish_issue(issue.id, normal=True, error=None)

    def finish_issue(self, issue_id: str, *, normal: bool, error: str | None) -> None:
        entry = self.state.running.pop(issue_id, None)
        if not entry:
            return
        if normal:
            self.state.completed.add(issue_id)
            self.schedule_retry(entry.issue, attempt=1, error=None, continuation=True)
        else:
            self.schedule_retry(entry.issue, attempt=1, error=error, continuation=False)

    def schedule_retry(self, issue: Issue, *, attempt: int, error: str | None, continuation: bool = False) -> None:
        delay = 1000 if continuation else min(10000 * (2 ** max(attempt - 1, 0)), self.config.max_retry_backoff_ms)
        self.state.retry_attempts[issue.id] = RetryEntry(
            issue_id=issue.id,
            identifier=issue.identifier,
            attempt=attempt,
            due_at_ms=monotonic_ms() + delay,
            error=error,
        )

    def retry_due(self, issue_id: str) -> None:
        retry = self.state.retry_attempts.pop(issue_id, None)
        if not retry:
            return
        try:
            candidates = self.tracker.fetch_candidate_issues()
        except TrackerError:
            issue = Issue(id=retry.issue_id, identifier=retry.identifier, title=retry.identifier, state="unknown")
            self.schedule_retry(issue, attempt=retry.attempt + 1, error="retry poll failed")
            return
        issue = next((candidate for candidate in candidates if candidate.id == issue_id), None)
        if issue is None:
            self.state.claimed.discard(issue_id)
            return
        self.state.claimed.discard(issue_id)
        if self.eligible(issue):
            self.dispatch_issue(issue, attempt=retry.attempt)
        else:
            self.schedule_retry(issue, attempt=retry.attempt + 1, error="no available orchestrator slots")

    def reconcile_running(self) -> None:
        self.reconcile_stalled()
        if not self.state.running:
            return
        try:
            refreshed = self.tracker.fetch_issue_states_by_ids(list(self.state.running))
        except TrackerError:
            return
        for issue in refreshed:
            if issue.id not in self.state.running:
                continue
            if self.config.is_terminal_state(issue.state):
                self.workspace_manager.cleanup_for_issue(issue.identifier)
                self.state.running.pop(issue.id, None)
                self.state.claimed.discard(issue.id)
            elif self.config.is_active_state(issue.state):
                self.state.running[issue.id].issue = issue
            else:
                self.state.running.pop(issue.id, None)
                self.state.claimed.discard(issue.id)

    def reconcile_stalled(self) -> None:
        if self.config.codex_stall_timeout_ms <= 0:
            return
        now = datetime.now(timezone.utc)
        for issue_id, entry in list(self.state.running.items()):
            marker = entry.last_codex_timestamp or entry.started_at
            elapsed_ms = int((now - marker).total_seconds() * 1000)
            if elapsed_ms > self.config.codex_stall_timeout_ms:
                self.finish_issue(issue_id, normal=False, error="stalled")

    def startup_terminal_cleanup(self) -> None:
        try:
            terminal_issues = self.tracker.fetch_issues_by_states(list(self.config.terminal_states))
        except TrackerError:
            return
        for issue in terminal_issues:
            self.workspace_manager.cleanup_for_issue(issue.identifier)

    def snapshot(self) -> dict[str, object]:
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "counts": {"running": len(self.state.running), "retrying": len(self.state.retry_attempts)},
            "running": [
                {
                    "issue_id": entry.issue.id,
                    "issue_identifier": entry.issue.identifier,
                    "state": entry.issue.state,
                    "session_id": entry.session_id,
                    "turn_count": entry.turn_count,
                    "last_event": entry.last_codex_event,
                    "last_message": entry.last_codex_message,
                    "started_at": entry.started_at.isoformat(),
                }
                for entry in self.state.running.values()
            ],
            "retrying": [retry.__dict__ for retry in self.state.retry_attempts.values()],
            "codex_totals": self.state.codex_totals,
            "rate_limits": self.state.codex_rate_limits,
        }
