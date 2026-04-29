import tempfile
import threading
import unittest
from concurrent.futures import Future, ThreadPoolExecutor
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


class BlockingRunner:
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()

    def run_turn(self, issue, prompt, workspace_path, attempt=None):
        self.started.set()
        self.release.wait(timeout=5)
        return AgentRunResult(success=True)


class InlineExecutor:
    def submit(self, fn, /, *args, **kwargs):
        future = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except Exception as exc:
            future.set_exception(exc)
        return future


class OrchestratorTests(unittest.TestCase):
    def build(self, root, tracker):
        runner = FakeRunner()
        orchestrator = Orchestrator(config(root), tracker, WorkspaceManager(config(root)), runner, "Work on {{ issue.identifier }}", executor=InlineExecutor())
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

    def test_dispatch_is_non_blocking_and_preserves_running_slot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cfg = config(root)
            tracker = FakeTracker(candidates=[issue("ABC-4", state="Todo")])
            runner = BlockingRunner()
            with ThreadPoolExecutor(max_workers=1) as executor:
                orchestrator = Orchestrator(cfg, tracker, WorkspaceManager(cfg), runner, "Work on {{ issue.identifier }}", executor=executor)
                orchestrator.tick_once()
                self.assertTrue(runner.started.wait(timeout=2))
                self.assertIn("abc-4", orchestrator.state.running)
                self.assertEqual(orchestrator.available_slots_for("Todo"), 0)
                runner.release.set()

    def test_process_due_retries_dispatches_only_due_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            candidate = issue("ABC-5", state="Todo")
            orchestrator, runner = self.build(Path(directory), FakeTracker(candidates=[candidate]))
            orchestrator.schedule_retry(candidate, attempt=1, error=None)
            orchestrator.state.retry_attempts[candidate.id].due_at_ms = 10**15
            orchestrator.process_due_retries()
            self.assertEqual(len(runner.prompts), 0)
            orchestrator.state.retry_attempts[candidate.id].due_at_ms = 0
            orchestrator.process_due_retries()
            self.assertEqual(len(runner.prompts), 1)
