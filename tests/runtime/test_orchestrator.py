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

    def test_apply_reload_updates_runtime_config_and_prompt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old_config = config(root)
            new_config = RuntimeConfig(
                workflow_path=root / "WORKFLOW.md",
                tracker_kind="linear",
                tracker_endpoint="https://api.linear.app/graphql",
                tracker_api_key="token",
                tracker_project_slug="project",
                active_states=("Ready",),
                terminal_states=("Done",),
                polling_interval_ms=1234,
                workspace_root=root / "new-workspaces",
                hooks={"after_create": None, "before_run": "echo before", "after_run": None, "before_remove": None},
                hooks_timeout_ms=2000,
                max_concurrent_agents=3,
                max_turns=20,
                max_retry_backoff_ms=300000,
                max_concurrent_agents_by_state={"ready": 2},
                codex_command="true",
                codex_turn_timeout_ms=1000,
                codex_read_timeout_ms=1000,
                codex_stall_timeout_ms=300000,
                approval_policy="on-request",
                thread_sandbox="workspace-write",
                turn_sandbox_policy="workspace-write",
            )
            runner = FakeRunner()
            orchestrator = Orchestrator(old_config, FakeTracker(), WorkspaceManager(old_config), runner, "old", executor=InlineExecutor())
            orchestrator.apply_reload(new_config, "new {{ issue.identifier }}")
            self.assertEqual(orchestrator.state.poll_interval_ms, 1234)
            self.assertEqual(orchestrator.state.max_concurrent_agents, 3)
            self.assertEqual(orchestrator.workspace_manager.root, (root / "new-workspaces").resolve())
            self.assertEqual(orchestrator.config.hooks["before_run"], "echo before")
            self.assertEqual(orchestrator.prompt_template, "new {{ issue.identifier }}")

    def test_per_state_concurrency_limits_dispatch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cfg = RuntimeConfig(
                **{
                    **config(root).__dict__,
                    "max_concurrent_agents": 3,
                    "max_concurrent_agents_by_state": {"todo": 1, "in progress": 2},
                }
            )
            tracker = FakeTracker(
                candidates=[
                    issue("TODO-1", state="Todo"),
                    issue("TODO-2", state="Todo"),
                    issue("IP-1", state="In Progress"),
                    issue("IP-2", state="In Progress"),
                ]
            )
            runner = BlockingRunner()
            with ThreadPoolExecutor(max_workers=3) as executor:
                orchestrator = Orchestrator(cfg, tracker, WorkspaceManager(cfg), runner, "Work on {{ issue.identifier }}", executor=executor)
                orchestrator.tick_once()
                self.assertTrue(runner.started.wait(timeout=2))
                self.assertEqual(len(orchestrator.state.running), 3)
                self.assertEqual(sum(1 for entry in orchestrator.state.running.values() if entry.issue.state == "Todo"), 1)
                self.assertEqual(sum(1 for entry in orchestrator.state.running.values() if entry.issue.state == "In Progress"), 2)
                runner.release.set()

    def test_global_concurrency_caps_state_specific_limits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cfg = RuntimeConfig(
                **{
                    **config(root).__dict__,
                    "max_concurrent_agents": 2,
                    "max_concurrent_agents_by_state": {"todo": 5},
                }
            )
            tracker = FakeTracker(candidates=[issue("TODO-1"), issue("TODO-2"), issue("TODO-3")])
            runner = BlockingRunner()
            with ThreadPoolExecutor(max_workers=2) as executor:
                orchestrator = Orchestrator(cfg, tracker, WorkspaceManager(cfg), runner, "Work on {{ issue.identifier }}", executor=executor)
                orchestrator.tick_once()
                self.assertTrue(runner.started.wait(timeout=2))
                self.assertEqual(len(orchestrator.state.running), 2)
                runner.release.set()

    def test_retry_backoff_is_capped_for_repeated_abnormal_exits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cfg = RuntimeConfig(**{**config(root).__dict__, "max_retry_backoff_ms": 25000})
            orchestrator = Orchestrator(cfg, FakeTracker(), WorkspaceManager(cfg), FakeRunner(), "Work", executor=InlineExecutor())
            candidate = issue("ABC-6")
            orchestrator.schedule_retry(candidate, attempt=1, error="failed")
            first_delay = orchestrator.state.retry_attempts[candidate.id].due_at_ms
            orchestrator.schedule_retry(candidate, attempt=10, error="failed")
            capped_delay = orchestrator.state.retry_attempts[candidate.id].due_at_ms
            self.assertLessEqual(capped_delay - first_delay, 25000)

    def test_continuation_retry_releases_claim_when_candidate_disappears(self):
        with tempfile.TemporaryDirectory() as directory:
            candidate = issue("ABC-7")
            orchestrator, _ = self.build(Path(directory), FakeTracker(candidates=[]))
            orchestrator.state.claimed.add(candidate.id)
            orchestrator.schedule_retry(candidate, attempt=1, error=None, continuation=True)
            orchestrator.state.retry_attempts[candidate.id].due_at_ms = 0
            orchestrator.process_due_retries()
            self.assertNotIn(candidate.id, orchestrator.state.claimed)
            self.assertNotIn(candidate.id, orchestrator.state.retry_attempts)

    def test_reconcile_non_active_non_terminal_stops_without_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paused = issue("ABC-8", state="Human Review")
            orchestrator, _ = self.build(root, FakeTracker(states=[paused]))
            workspace = orchestrator.workspace_manager.create_for_issue(paused.identifier)
            orchestrator.state.claimed.add(paused.id)
            orchestrator.state.running[paused.id] = RunningEntry(issue=issue("ABC-8", state="In Progress"), started_at=datetime.now(timezone.utc), workspace_path=workspace.path)
            orchestrator.reconcile_running()
            self.assertTrue(workspace.path.exists())
            self.assertNotIn(paused.id, orchestrator.state.running)
            self.assertNotIn(paused.id, orchestrator.state.claimed)
