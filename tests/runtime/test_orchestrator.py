import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from harness.runtime.agent import AgentRunResult
from harness.runtime.models import BlockerRef, Issue, RuntimeConfig, RunningEntry
from harness.runtime.orchestrator import Orchestrator
from harness.runtime.workspace import WorkspaceManager


def issue(identifier, *, state="Todo", priority=None, created_at=None, blocked_by=()):
    return Issue(
        id=identifier.lower(),
        identifier=identifier,
        title=f"{identifier} title",
        state=state,
        priority=priority,
        created_at=created_at,
        blocked_by=blocked_by,
    )


def config(root: Path) -> RuntimeConfig:
    return RuntimeConfig(
        workflow_path=root / "WORKFLOW.md",
        tracker_kind="linear",
        tracker_endpoint="https://api.linear.app/graphql",
        tracker_api_key="token",
        tracker_project_slug="project",
        active_states=("Todo", "In Progress"),
        terminal_states=("Done", "Cancelled"),
        polling_interval_ms=30000,
        workspace_root=root,
        hooks={"after_create": None, "before_run": None, "after_run": None, "before_remove": None},
        hooks_timeout_ms=1000,
        max_concurrent_agents=1,
        max_turns=20,
        max_retry_backoff_ms=300000,
        max_concurrent_agents_by_state={},
        codex_command="true",
        codex_turn_timeout_ms=1000,
        codex_read_timeout_ms=1000,
        codex_stall_timeout_ms=1,
        approval_policy="on-request",
        thread_sandbox="workspace-write",
        turn_sandbox_policy="workspace-write",
    )


class FakeTracker:
    def __init__(self, candidates=None, states=None, terminal=None):
        self.candidates = candidates or []
        self.states = states or []
        self.terminal = terminal or []

    def fetch_candidate_issues(self):
        return list(self.candidates)

    def fetch_issues_by_states(self, state_names):
        return list(self.terminal)

    def fetch_issue_states_by_ids(self, issue_ids):
        return list(self.states)


class FakeRunner:
    def __init__(self):
        self.prompts = []

    def run_turn(self, issue, prompt, workspace_path, attempt=None):
        self.prompts.append((issue, prompt, workspace_path, attempt))
        return AgentRunResult(success=True)


class OrchestratorTests(unittest.TestCase):
    def build(self, root, tracker):
        runner = FakeRunner()
        orchestrator = Orchestrator(config(root), tracker, WorkspaceManager(config(root)), runner, "Work on {{ issue.identifier }}")
        return orchestrator, runner

    def test_todo_blocked_by_non_terminal_is_not_eligible(self):
        with tempfile.TemporaryDirectory() as directory:
            blocked = issue("ABC-1", blocked_by=(BlockerRef(identifier="ABC-0", state="In Progress"),))
            orchestrator, _ = self.build(Path(directory), FakeTracker())
            self.assertFalse(orchestrator.eligible(blocked))

    def test_sort_order_priority_then_created(self):
        with tempfile.TemporaryDirectory() as directory:
            old = datetime(2024, 1, 1, tzinfo=timezone.utc)
            new = datetime(2025, 1, 1, tzinfo=timezone.utc)
            issues = [issue("B", priority=None, created_at=old), issue("C", priority=2, created_at=new), issue("A", priority=1, created_at=new)]
            orchestrator, _ = self.build(Path(directory), FakeTracker())
            self.assertEqual([item.identifier for item in orchestrator.sort_for_dispatch(issues)], ["A", "C", "B"])

    def test_tick_dispatches_and_schedules_continuation_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            candidate = issue("ABC-1", state="Todo")
            orchestrator, runner = self.build(Path(directory), FakeTracker(candidates=[candidate]))
            orchestrator.tick_once()
            self.assertEqual(len(runner.prompts), 1)
            self.assertIn(candidate.id, orchestrator.state.retry_attempts)

    def test_reconcile_terminal_cleans_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            done = issue("ABC-2", state="Done")
            orchestrator, _ = self.build(root, FakeTracker(states=[done]))
            workspace = orchestrator.workspace_manager.create_for_issue(done.identifier)
            orchestrator.state.running[done.id] = RunningEntry(issue=issue("ABC-2", state="In Progress"), started_at=datetime.now(timezone.utc), workspace_path=workspace.path)
            orchestrator.reconcile_running()
            self.assertFalse(workspace.path.exists())

    def test_stall_detection_schedules_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            stale = issue("ABC-3", state="In Progress")
            orchestrator, _ = self.build(Path(directory), FakeTracker())
            orchestrator.state.running[stale.id] = RunningEntry(issue=stale, started_at=datetime.now(timezone.utc) - timedelta(seconds=5))
            orchestrator.reconcile_stalled()
            self.assertIn(stale.id, orchestrator.state.retry_attempts)
