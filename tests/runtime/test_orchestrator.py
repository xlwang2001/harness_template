import json
import logging
import tempfile
import threading
import unittest
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from harness.runtime.agent import AgentRunnerError, AgentRunResult
from harness.runtime.models import BlockerRef, Issue, RetryEntry, RunAttemptRecord, RuntimeConfig, RunningEntry
from harness.runtime.orchestrator import Orchestrator
from harness.runtime.tracker import TrackerError
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
        self.candidate_fetches = 0
        self.state_fetches = 0
        self.terminal_fetches = 0
        self.terminal_state_names = []

    def fetch_candidate_issues(self):
        self.candidate_fetches += 1
        return list(self.candidates)

    def fetch_issues_by_states(self, state_names):
        self.terminal_fetches += 1
        self.terminal_state_names.append(tuple(state_names))
        return list(self.terminal)

    def fetch_issue_states_by_ids(self, issue_ids):
        self.state_fetches += 1
        return list(self.states)


class SequenceStateTracker(FakeTracker):
    def __init__(self, candidates=None, state_batches=None):
        super().__init__(candidates=candidates)
        self.state_batches = list(state_batches or [])

    def fetch_issue_states_by_ids(self, issue_ids):
        self.state_fetches += 1
        if not self.state_batches:
            return []
        return list(self.state_batches.pop(0))


class FailingTerminalTracker(FakeTracker):
    def fetch_issues_by_states(self, state_names):
        raise TrackerError("terminal fetch failed")


class FakeRunner:
    def __init__(self):
        self.prompts = []

    def run_turn(self, issue, prompt, workspace_path, attempt=None, on_event=None):
        self.prompts.append((issue, prompt, workspace_path, attempt))
        return AgentRunResult(success=True)


class FailingRunner(FakeRunner):
    def run_turn(self, issue, prompt, workspace_path, attempt=None, on_event=None):
        super().run_turn(issue, prompt, workspace_path, attempt, on_event=on_event)
        raise AgentRunnerError("agent failed")


class TimeoutRunner(FakeRunner):
    def run_turn(self, issue, prompt, workspace_path, attempt=None, on_event=None):
        super().run_turn(issue, prompt, workspace_path, attempt, on_event=on_event)
        raise AgentRunnerError("turn_timeout")


class EventRunner(FakeRunner):
    def __init__(self, events):
        super().__init__()
        self.events = events

    def run_turn(self, issue, prompt, workspace_path, attempt=None, on_event=None):
        super().run_turn(issue, prompt, workspace_path, attempt, on_event=on_event)
        if on_event is not None:
            for event in self.events:
                on_event(event)
        return AgentRunResult(success=True, events=tuple(self.events))


class SessionRunner(FakeRunner):
    def __init__(self):
        super().__init__()
        self.continuation_prompts = []

    def run_session(self, issue, prompt, continuation_prompt, workspace_path, attempt=None, *, max_turns, should_continue, on_event=None):
        completed = 0
        while completed < max_turns:
            current_prompt = prompt if completed == 0 else continuation_prompt
            self.prompts.append((issue, current_prompt, workspace_path, attempt))
            self.continuation_prompts.append(current_prompt)
            if on_event is not None:
                on_event({"event": "session_started", "session_id": f"thread-1-turn-{completed + 1}", "thread_id": "thread-1", "turn_id": f"turn-{completed + 1}"})
                on_event({"event": "turn_completed", "turn_id": f"turn-{completed + 1}"})
            completed += 1
            if completed >= max_turns:
                break
            if not should_continue(completed):
                break
        return AgentRunResult(success=True, session_id=f"thread-1-turn-{completed}", turn_count=completed)


class BlockingRunner:
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()

    def run_turn(self, issue, prompt, workspace_path, attempt=None, on_event=None):
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


class QueuedExecutor:
    def __init__(self):
        self.futures = []

    def submit(self, fn, /, *args, **kwargs):
        future = Future()
        self.futures.append(future)
        return future


class ShutdownExecutor(QueuedExecutor):
    def __init__(self):
        super().__init__()
        self.shutdown_calls = []

    def shutdown(self, **kwargs):
        self.shutdown_calls.append(kwargs)


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

    def test_worker_continues_on_same_session_while_issue_remains_active(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = issue("ABC-34", state="Todo")
            cfg = RuntimeConfig(**{**config(root).__dict__, "max_turns": 3})
            tracker = SequenceStateTracker(
                candidates=[candidate],
                state_batches=[
                    [issue("ABC-34", state="In Progress")],
                    [issue("ABC-34", state="In Progress")],
                ],
            )
            runner = SessionRunner()
            orchestrator = Orchestrator(cfg, tracker, WorkspaceManager(cfg), runner, "Work on {{ issue.identifier }}", executor=InlineExecutor())

            orchestrator.tick_once()

            self.assertEqual(len(runner.prompts), 3)
            self.assertEqual(runner.prompts[0][1], "Work on ABC-34")
            self.assertEqual(runner.prompts[1][1], "Continue working on this issue. Inspect the current workspace state and proceed with the next useful step.")
            self.assertEqual(runner.prompts[2][1], "Continue working on this issue. Inspect the current workspace state and proceed with the next useful step.")
            self.assertEqual(tracker.state_fetches, 2)
            self.assertEqual(orchestrator.state.last_attempts[candidate.id].status, "succeeded")
            self.assertIn(candidate.id, orchestrator.state.retry_attempts)

    def test_worker_stops_continuation_when_issue_leaves_active_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = issue("ABC-35", state="Todo")
            cfg = RuntimeConfig(**{**config(root).__dict__, "max_turns": 3})
            tracker = SequenceStateTracker(
                candidates=[candidate],
                state_batches=[[issue("ABC-35", state="Human Review")]],
            )
            runner = SessionRunner()
            orchestrator = Orchestrator(cfg, tracker, WorkspaceManager(cfg), runner, "Work on {{ issue.identifier }}", executor=InlineExecutor())

            orchestrator.tick_once()

            self.assertEqual(len(runner.prompts), 1)
            self.assertEqual(tracker.state_fetches, 1)
            self.assertIn(candidate.id, orchestrator.state.retry_attempts)

    def test_worker_continuation_state_refresh_failure_schedules_retry(self):
        class FailingStateTracker(FakeTracker):
            def fetch_issue_states_by_ids(self, issue_ids):
                self.state_fetches += 1
                raise TrackerError("state refresh failed")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = issue("ABC-36", state="Todo")
            cfg = RuntimeConfig(**{**config(root).__dict__, "max_turns": 3})
            tracker = FailingStateTracker(candidates=[candidate])
            runner = SessionRunner()
            orchestrator = Orchestrator(cfg, tracker, WorkspaceManager(cfg), runner, "Work", executor=InlineExecutor())

            orchestrator.tick_once()

            self.assertEqual(len(runner.prompts), 1)
            self.assertEqual(orchestrator.state.last_attempts[candidate.id].status, "failed")
            self.assertEqual(orchestrator.state.retry_attempts[candidate.id].attempt, 1)

    def test_successful_worker_records_succeeded_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = issue("ABC-25", state="Todo")
            orchestrator, _ = self.build(root, FakeTracker(candidates=[candidate]))

            orchestrator.tick_once()

            record = orchestrator.state.last_attempts[candidate.id]
            self.assertEqual(record.issue_id, candidate.id)
            self.assertEqual(record.identifier, "ABC-25")
            self.assertIsNone(record.attempt)
            self.assertEqual(record.workspace_path, root / "ABC-25")
            self.assertEqual(record.status, "succeeded")
            self.assertIsNone(record.error)
            self.assertLessEqual(record.started_at, record.finished_at)
            self.assertIn(candidate.id, orchestrator.state.retry_attempts)

    def test_failed_worker_records_failed_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = issue("ABC-26", state="Todo")
            cfg = config(root)
            orchestrator = Orchestrator(cfg, FakeTracker(candidates=[candidate]), WorkspaceManager(cfg), FailingRunner(), "Work", executor=InlineExecutor())

            orchestrator.tick_once()

            record = orchestrator.state.last_attempts[candidate.id]
            self.assertEqual(record.status, "failed")
            self.assertEqual(record.error, "agent failed")
            self.assertEqual(record.workspace_path, root / "ABC-26")
            self.assertIn(candidate.id, orchestrator.state.retry_attempts)

    def test_turn_timeout_worker_records_timed_out_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = issue("ABC-27", state="Todo")
            cfg = config(root)
            orchestrator = Orchestrator(cfg, FakeTracker(candidates=[candidate]), WorkspaceManager(cfg), TimeoutRunner(), "Work", executor=InlineExecutor())

            orchestrator.tick_once()

            record = orchestrator.state.last_attempts[candidate.id]
            self.assertEqual(record.status, "timed_out")
            self.assertEqual(record.error, "turn_timeout")
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
            self.assertEqual(orchestrator.state.last_attempts[done.id].status, "canceled_by_reconciliation")

    def test_reconcile_terminal_cancels_pending_future_and_does_not_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            running = issue("ABC-12", state="Todo")
            done = issue("ABC-12", state="Done")
            executor = QueuedExecutor()
            orchestrator = Orchestrator(config(root), FakeTracker(candidates=[running], states=[done]), WorkspaceManager(config(root)), FakeRunner(), "Work", executor=executor)
            workspace = orchestrator.workspace_manager.create_for_issue(running.identifier)
            orchestrator.tick_once()
            orchestrator.reconcile_running()
            self.assertTrue(executor.futures[0].cancelled())
            self.assertFalse(workspace.path.exists())
            self.assertNotIn(running.id, orchestrator.state.running)
            self.assertNotIn(running.id, orchestrator.state.worker_futures)
            self.assertNotIn(running.id, orchestrator.state.claimed)
            self.assertNotIn(running.id, orchestrator.state.retry_attempts)

    def test_stall_detection_schedules_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            stale = issue("ABC-3", state="In Progress")
            orchestrator, _ = self.build(Path(directory), FakeTracker())
            orchestrator.state.running[stale.id] = RunningEntry(issue=stale, started_at=datetime.now(timezone.utc) - timedelta(seconds=5))
            orchestrator.reconcile_stalled()
            self.assertIn(stale.id, orchestrator.state.retry_attempts)
            record = orchestrator.state.last_attempts[stale.id]
            self.assertEqual(record.status, "stalled")
            self.assertEqual(record.error, "stalled")

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
                self.assertIn("abc-4", orchestrator.state.worker_futures)
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

    def test_tick_preflight_failure_reconciles_running_but_skips_candidate_dispatch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cfg = RuntimeConfig(**{**config(root).__dict__, "tracker_project_slug": None})
            done = issue("ABC-18", state="Done")
            tracker = FakeTracker(candidates=[issue("ABC-19")], states=[done])
            runner = FakeRunner()
            orchestrator = Orchestrator(cfg, tracker, WorkspaceManager(cfg), runner, "Work", executor=InlineExecutor())
            workspace = orchestrator.workspace_manager.create_for_issue(done.identifier)
            orchestrator.state.running[done.id] = RunningEntry(issue=issue("ABC-18", state="In Progress"), started_at=datetime.now(timezone.utc), workspace_path=workspace.path)

            orchestrator.tick_once()

            self.assertEqual(tracker.state_fetches, 1)
            self.assertEqual(tracker.candidate_fetches, 0)
            self.assertFalse(workspace.path.exists())
            self.assertEqual(runner.prompts, [])

    def test_tick_preflight_failure_leaves_due_retry_queued(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cfg = RuntimeConfig(**{**config(root).__dict__, "tracker_project_slug": None})
            candidate = issue("ABC-20")
            tracker = FakeTracker(candidates=[candidate])
            runner = FakeRunner()
            orchestrator = Orchestrator(cfg, tracker, WorkspaceManager(cfg), runner, "Work", executor=InlineExecutor())
            orchestrator.schedule_retry(candidate, attempt=1, error="temporary")
            orchestrator.state.retry_attempts[candidate.id].due_at_ms = 0

            orchestrator.tick_once()

            self.assertEqual(tracker.candidate_fetches, 0)
            self.assertEqual(runner.prompts, [])
            self.assertIn(candidate.id, orchestrator.state.retry_attempts)

    def test_tick_preflight_failure_logs_without_secret(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            secret = "super-secret-token"
            cfg = RuntimeConfig(**{**config(root).__dict__, "tracker_api_key": secret, "tracker_project_slug": None})
            logger = logging.getLogger("harness.runtime.test.preflight")
            orchestrator = Orchestrator(cfg, FakeTracker(), WorkspaceManager(cfg, logger=logger), FakeRunner(), "Work", executor=InlineExecutor(), logger=logger)

            with self.assertLogs(logger, level="ERROR") as captured:
                orchestrator.tick_once()

            output = "\n".join(captured.output)
            self.assertIn("event=dispatch_preflight_failed", output)
            self.assertIn("tracker.project_slug is required for Linear", output)
            self.assertNotIn(secret, output)

    def test_after_run_hook_runs_after_successful_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cfg = RuntimeConfig(
                **{
                    **config(root).__dict__,
                    "hooks": {"after_create": None, "before_run": None, "after_run": "printf success > after_run.txt", "before_remove": None},
                }
            )
            candidate = issue("ABC-21")
            orchestrator = Orchestrator(cfg, FakeTracker(candidates=[candidate]), WorkspaceManager(cfg), FakeRunner(), "Work", executor=InlineExecutor())

            orchestrator.tick_once()

            self.assertEqual((root / "ABC-21" / "after_run.txt").read_text(encoding="utf-8"), "success")
            self.assertIn(candidate.id, orchestrator.state.retry_attempts)

    def test_after_run_hook_runs_after_agent_failure_once_workspace_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cfg = RuntimeConfig(
                **{
                    **config(root).__dict__,
                    "hooks": {"after_create": None, "before_run": None, "after_run": "printf failed > after_run.txt", "before_remove": None},
                }
            )
            candidate = issue("ABC-22")
            orchestrator = Orchestrator(cfg, FakeTracker(candidates=[candidate]), WorkspaceManager(cfg), FailingRunner(), "Work", executor=InlineExecutor())

            orchestrator.tick_once()

            self.assertEqual((root / "ABC-22" / "after_run.txt").read_text(encoding="utf-8"), "failed")
            self.assertIn(candidate.id, orchestrator.state.retry_attempts)
            self.assertEqual(orchestrator.state.retry_attempts[candidate.id].error, "agent failed")

    def test_after_run_hook_runs_after_before_run_failure_once_workspace_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cfg = RuntimeConfig(
                **{
                    **config(root).__dict__,
                    "hooks": {"after_create": None, "before_run": "exit 1", "after_run": "printf before_failed > after_run.txt", "before_remove": None},
                }
            )
            candidate = issue("ABC-23")
            runner = FakeRunner()
            orchestrator = Orchestrator(cfg, FakeTracker(candidates=[candidate]), WorkspaceManager(cfg), runner, "Work", executor=InlineExecutor())

            orchestrator.tick_once()

            self.assertEqual((root / "ABC-23" / "after_run.txt").read_text(encoding="utf-8"), "before_failed")
            self.assertEqual(runner.prompts, [])
            self.assertIn(candidate.id, orchestrator.state.retry_attempts)

    def test_after_run_hook_runs_when_attempt_is_canceled_after_workspace_create(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cfg = RuntimeConfig(
                **{
                    **config(root).__dict__,
                    "hooks": {"after_create": None, "before_run": None, "after_run": "printf canceled > after_run.txt", "before_remove": None},
                }
            )
            candidate = issue("ABC-24")
            orchestrator = Orchestrator(cfg, FakeTracker(), WorkspaceManager(cfg), FakeRunner(), "Work", executor=InlineExecutor())
            orchestrator.state.running[candidate.id] = RunningEntry(issue=candidate, started_at=datetime.now(timezone.utc))
            orchestrator.state.running.pop(candidate.id)

            orchestrator._run_issue(candidate, attempt=None)

            self.assertEqual((root / "ABC-24" / "after_run.txt").read_text(encoding="utf-8"), "canceled")
            self.assertNotIn(candidate.id, orchestrator.state.retry_attempts)

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

    def test_retried_abnormal_exit_increments_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = issue("ABC-31")
            cfg = config(root)
            orchestrator = Orchestrator(cfg, FakeTracker(candidates=[candidate]), WorkspaceManager(cfg), FailingRunner(), "Work", executor=InlineExecutor())
            orchestrator.schedule_retry(candidate, attempt=2, error="previous failure")
            orchestrator.state.retry_attempts[candidate.id].due_at_ms = 0

            orchestrator.process_due_retries()

            self.assertEqual(orchestrator.state.last_attempts[candidate.id].attempt, 2)
            self.assertEqual(orchestrator.state.retry_attempts[candidate.id].attempt, 3)

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
            self.assertEqual(orchestrator.state.last_attempts[paused.id].status, "canceled_by_reconciliation")
            self.assertIsNone(orchestrator.state.last_attempts[paused.id].error)
            self.assertNotIn(paused.id, orchestrator.state.retry_attempts)

    def test_reconcile_non_active_cancels_pending_future_without_cleanup_or_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            running = issue("ABC-13", state="Todo")
            paused = issue("ABC-13", state="Human Review")
            executor = QueuedExecutor()
            orchestrator = Orchestrator(config(root), FakeTracker(candidates=[running], states=[paused]), WorkspaceManager(config(root)), FakeRunner(), "Work", executor=executor)
            workspace = orchestrator.workspace_manager.create_for_issue(running.identifier)
            orchestrator.tick_once()
            orchestrator.reconcile_running()
            self.assertTrue(executor.futures[0].cancelled())
            self.assertTrue(workspace.path.exists())
            self.assertNotIn(running.id, orchestrator.state.running)
            self.assertNotIn(running.id, orchestrator.state.worker_futures)
            self.assertNotIn(running.id, orchestrator.state.claimed)
            self.assertNotIn(running.id, orchestrator.state.retry_attempts)

    def test_startup_terminal_cleanup_runs_before_remove_hook_and_removes_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            done = issue("ABC-9", state="Done")
            cfg = RuntimeConfig(
                **{
                    **config(root).__dict__,
                    "hooks": {"after_create": None, "before_run": None, "after_run": None, "before_remove": "printf removed > ../removed.txt"},
                }
            )
            orchestrator = Orchestrator(cfg, FakeTracker(terminal=[done]), WorkspaceManager(cfg), FakeRunner(), "Work", executor=InlineExecutor())
            workspace = orchestrator.workspace_manager.create_for_issue(done.identifier)
            orchestrator.startup_terminal_cleanup()
            self.assertFalse(workspace.path.exists())
            self.assertEqual((root / "removed.txt").read_text(encoding="utf-8"), "removed")

    def test_startup_terminal_cleanup_keeps_running_when_terminal_fetch_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            done = issue("ABC-10", state="Done")
            orchestrator = Orchestrator(config(root), FailingTerminalTracker(), WorkspaceManager(config(root)), FakeRunner(), "Work", executor=InlineExecutor())
            workspace = orchestrator.workspace_manager.create_for_issue(done.identifier)
            orchestrator.startup_terminal_cleanup()
            self.assertTrue(workspace.path.exists())

    def test_startup_terminal_cleanup_removes_workspace_after_nonfatal_hook_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            done = issue("ABC-11", state="Done")
            cfg = RuntimeConfig(
                **{
                    **config(root).__dict__,
                    "hooks": {"after_create": None, "before_run": None, "after_run": None, "before_remove": "exit 1"},
                }
            )
            orchestrator = Orchestrator(cfg, FakeTracker(terminal=[done]), WorkspaceManager(cfg), FakeRunner(), "Work", executor=InlineExecutor())
            workspace = orchestrator.workspace_manager.create_for_issue(done.identifier)
            orchestrator.startup_terminal_cleanup()
            self.assertFalse(workspace.path.exists())

    def test_restart_recovery_starts_with_empty_runtime_state_and_reuses_preserved_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = issue("ABC-37", state="Todo")
            cfg = RuntimeConfig(
                **{
                    **config(root).__dict__,
                    "hooks": {
                        "after_create": "printf created > marker.txt",
                        "before_run": None,
                        "after_run": None,
                        "before_remove": None,
                    },
                }
            )
            first = Orchestrator(cfg, FakeTracker(), WorkspaceManager(cfg), FakeRunner(), "Work", executor=InlineExecutor())
            workspace = first.workspace_manager.create_for_issue(candidate.identifier)
            (workspace.path / "marker.txt").write_text("preserved", encoding="utf-8")
            first.state.running[candidate.id] = RunningEntry(issue=candidate, started_at=datetime.now(timezone.utc), workspace_path=workspace.path)
            first.schedule_retry(candidate, attempt=4, error="old process")

            runner = FakeRunner()
            restarted = Orchestrator(cfg, FakeTracker(candidates=[candidate]), WorkspaceManager(cfg), runner, "Work", executor=InlineExecutor())

            self.assertEqual(restarted.state.running, {})
            self.assertEqual(restarted.state.retry_attempts, {})
            self.assertEqual(restarted.state.claimed, set())

            restarted.tick_once()

            self.assertEqual((workspace.path / "marker.txt").read_text(encoding="utf-8"), "preserved")
            self.assertEqual(len(runner.prompts), 1)
            self.assertEqual(runner.prompts[0][2], workspace.path)

    def test_opt_in_runtime_state_restores_retry_attempt_and_session_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = issue("ABC-40", state="Todo")
            state_file = root / ".harness" / "runtime-state.json"
            cfg = RuntimeConfig(
                **{
                    **config(root).__dict__,
                    "runtime_state_file": state_file,
                    "runtime_state_persist_retries": True,
                    "runtime_state_persist_sessions": True,
                }
            )
            first = Orchestrator(cfg, FakeTracker(), WorkspaceManager(cfg), FakeRunner(), "Work", executor=InlineExecutor())
            first.schedule_retry(candidate, attempt=4, error="old process")
            first.state.retry_attempts[candidate.id].due_at_ms = 0
            started = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
            finished = datetime(2026, 1, 1, 12, 2, tzinfo=timezone.utc)
            first.state.last_attempts[candidate.id] = RunAttemptRecord(
                issue_id=candidate.id,
                identifier=candidate.identifier,
                attempt=3,
                workspace_path=root / "ABC-40",
                started_at=started,
                finished_at=finished,
                status="failed",
                error="agent failed",
            )
            first.state.completed.add("abc-previous")
            first.state.codex_totals["input_tokens"] = 12
            first.state.codex_rate_limits = {"primary": {"remaining": 6}}
            first.state.session_metadata[candidate.id] = {
                "issue_identifier": candidate.identifier,
                "session_id": "session-40",
                "thread_id": "thread-40",
                "turn_id": "turn-3",
                "turn_count": 3,
                "last_codex_event": "turn_failed",
            }
            first.state.running[candidate.id] = RunningEntry(issue=candidate, started_at=started)
            first.state.claimed.add(candidate.id)
            first.state.worker_futures[candidate.id] = Future()
            first._persist_state()

            runner = FakeRunner()
            restarted = Orchestrator(cfg, FakeTracker(candidates=[candidate]), WorkspaceManager(cfg), runner, "Work", executor=InlineExecutor())

            self.assertEqual(restarted.state.running, {})
            self.assertEqual(restarted.state.claimed, set())
            self.assertEqual(restarted.state.worker_futures, {})
            self.assertEqual(restarted.state.retry_attempts[candidate.id].attempt, 4)
            self.assertEqual(restarted.state.retry_attempts[candidate.id].due_at_ms, 0)
            self.assertEqual(restarted.state.last_attempts[candidate.id].status, "failed")
            self.assertEqual(restarted.state.completed, {"abc-previous"})
            self.assertEqual(restarted.state.codex_totals["input_tokens"], 12)
            self.assertEqual(restarted.state.codex_rate_limits, {"primary": {"remaining": 6}})
            self.assertEqual(restarted.state.session_metadata[candidate.id]["session_id"], "session-40")

    def test_restored_due_retry_dispatches_when_candidate_reappears(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = issue("ABC-41", state="Todo")
            state_file = root / "runtime-state.json"
            cfg = RuntimeConfig(
                **{
                    **config(root).__dict__,
                    "runtime_state_file": state_file,
                    "runtime_state_persist_retries": True,
                    "runtime_state_persist_sessions": True,
                }
            )
            first = Orchestrator(cfg, FakeTracker(), WorkspaceManager(cfg), FakeRunner(), "Work", executor=InlineExecutor())
            first.schedule_retry(candidate, attempt=2, error="agent failed")
            first.state.retry_attempts[candidate.id].due_at_ms = 0
            first._persist_state()

            runner = FakeRunner()
            restarted = Orchestrator(cfg, FakeTracker(candidates=[candidate]), WorkspaceManager(cfg), runner, "Work", executor=InlineExecutor())

            restarted.process_due_retries()

            self.assertEqual(len(runner.prompts), 1)
            self.assertEqual(runner.prompts[0][3], 2)
            self.assertEqual(restarted.state.last_attempts[candidate.id].attempt, 2)
            self.assertEqual(restarted.state.retry_attempts[candidate.id].attempt, 1)

    def test_runtime_state_file_omits_tracker_secret_and_live_ownership(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            secret = "linear-secret-token"
            candidate = issue("ABC-42")
            state_file = root / "runtime-state.json"
            cfg = RuntimeConfig(
                **{
                    **config(root).__dict__,
                    "tracker_api_key": secret,
                    "runtime_state_file": state_file,
                    "runtime_state_persist_retries": True,
                    "runtime_state_persist_sessions": True,
                }
            )
            orchestrator = Orchestrator(cfg, FakeTracker(), WorkspaceManager(cfg), FakeRunner(), "Work", executor=InlineExecutor())
            orchestrator.state.running[candidate.id] = RunningEntry(
                issue=candidate,
                started_at=datetime.now(timezone.utc),
                codex_app_server_pid="12345",
            )
            orchestrator.state.claimed.add(candidate.id)
            orchestrator.state.worker_futures[candidate.id] = Future()
            orchestrator.schedule_retry(candidate, attempt=1, error="failed")
            orchestrator._persist_state()

            payload_text = state_file.read_text(encoding="utf-8")
            payload = json.loads(payload_text)
            self.assertNotIn(secret, payload_text)
            self.assertNotIn("running", payload)
            self.assertNotIn("claimed", payload)
            self.assertNotIn("worker_futures", payload)
            self.assertNotIn("codex_app_server_pid", payload_text)

    def test_startup_terminal_cleanup_handles_multiple_sanitized_and_missing_workspaces(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            terminal = [
                issue("ABC/unsafe one", state="Done"),
                issue("ABC unsafe two", state="Cancelled"),
                issue("ABC missing", state="Done"),
            ]
            cfg = RuntimeConfig(
                **{
                    **config(root).__dict__,
                    "hooks": {
                        "after_create": None,
                        "before_run": None,
                        "after_run": None,
                        "before_remove": "printf \"$PWD\\n\" >> ../removed.txt; exit 1",
                    },
                }
            )
            orchestrator = Orchestrator(cfg, FakeTracker(terminal=terminal), WorkspaceManager(cfg), FakeRunner(), "Work", executor=InlineExecutor())
            unsafe_one = orchestrator.workspace_manager.create_for_issue("ABC/unsafe one")
            unsafe_two = orchestrator.workspace_manager.create_for_issue("ABC unsafe two")

            orchestrator.startup_terminal_cleanup()

            self.assertFalse(unsafe_one.path.exists())
            self.assertFalse(unsafe_two.path.exists())
            self.assertFalse((root / "ABC_missing").exists())
            removed = (root / "removed.txt").read_text(encoding="utf-8")
            self.assertIn(str(root / "ABC_unsafe_one"), removed)
            self.assertIn(str(root / "ABC_unsafe_two"), removed)

    def test_startup_terminal_cleanup_logs_and_continues_when_one_cleanup_raises(self):
        class PartiallyFailingWorkspaceManager(WorkspaceManager):
            def __init__(self, cfg):
                super().__init__(cfg)
                self.cleaned = []

            def cleanup_for_issue(self, identifier):
                if identifier == "ABC-FAIL":
                    raise RuntimeError("cleanup failed")
                self.cleaned.append(identifier)
                return super().cleanup_for_issue(identifier)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cfg = config(root)
            manager = PartiallyFailingWorkspaceManager(cfg)
            failing = issue("ABC-FAIL", state="Done")
            passing = issue("ABC-PASS", state="Done")
            workspace = manager.create_for_issue(passing.identifier)
            orchestrator = Orchestrator(cfg, FakeTracker(terminal=[failing, passing]), manager, FakeRunner(), "Work", executor=InlineExecutor())

            orchestrator.startup_terminal_cleanup()

            self.assertFalse(workspace.path.exists())
            self.assertEqual(manager.cleaned, ["ABC-PASS"])

    def test_reconcile_missing_refreshed_state_stops_without_cleanup_or_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            running = issue("ABC-38", state="In Progress")
            tracker = FakeTracker(candidates=[running], states=[])
            executor = QueuedExecutor()
            orchestrator = Orchestrator(config(root), tracker, WorkspaceManager(config(root)), FakeRunner(), "Work", executor=executor)
            workspace = orchestrator.workspace_manager.create_for_issue(running.identifier)
            orchestrator.tick_once()
            orchestrator.state.running[running.id].workspace_path = workspace.path

            orchestrator.reconcile_running()

            self.assertTrue(workspace.path.exists())
            self.assertTrue(executor.futures[0].cancelled())
            self.assertNotIn(running.id, orchestrator.state.running)
            self.assertNotIn(running.id, orchestrator.state.worker_futures)
            self.assertNotIn(running.id, orchestrator.state.claimed)
            self.assertNotIn(running.id, orchestrator.state.retry_attempts)
            self.assertEqual(orchestrator.state.last_attempts[running.id].status, "canceled_by_reconciliation")

    def test_due_failure_retry_releases_stale_claim_when_candidate_disappears(self):
        with tempfile.TemporaryDirectory() as directory:
            candidate = issue("ABC-39")
            orchestrator, _ = self.build(Path(directory), FakeTracker(candidates=[]))
            orchestrator.state.claimed.add(candidate.id)
            orchestrator.schedule_retry(candidate, attempt=3, error="agent failed", continuation=False)
            orchestrator.state.retry_attempts[candidate.id].due_at_ms = 0

            orchestrator.process_due_retries()

            self.assertNotIn(candidate.id, orchestrator.state.claimed)
            self.assertNotIn(candidate.id, orchestrator.state.retry_attempts)

    def test_startup_terminal_cleanup_queries_configured_terminal_states(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tracker = FakeTracker(terminal=[])
            orchestrator = Orchestrator(config(root), tracker, WorkspaceManager(config(root)), FakeRunner(), "Work", executor=InlineExecutor())

            orchestrator.startup_terminal_cleanup()

            self.assertEqual(tracker.terminal_state_names, [("Done", "Cancelled")])

    def test_shutdown_cancels_pending_futures_clears_state_and_preserves_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = issue("ABC-14", state="Todo")
            executor = ShutdownExecutor()
            orchestrator = Orchestrator(config(root), FakeTracker(candidates=[candidate]), WorkspaceManager(config(root)), FakeRunner(), "Work", executor=executor)
            workspace = orchestrator.workspace_manager.create_for_issue(candidate.identifier)
            orchestrator.tick_once()
            orchestrator.shutdown("operator")
            self.assertTrue(executor.futures[0].cancelled())
            self.assertEqual(executor.shutdown_calls, [{"wait": False, "cancel_futures": True}])
            self.assertTrue(workspace.path.exists())
            self.assertEqual(orchestrator.state.running, {})
            self.assertEqual(orchestrator.state.worker_futures, {})
            self.assertEqual(orchestrator.state.claimed, set())
            self.assertEqual(orchestrator.state.retry_attempts, {})

    def test_late_future_completion_after_shutdown_does_not_schedule_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = issue("ABC-15", state="Todo")
            executor = QueuedExecutor()
            orchestrator = Orchestrator(config(root), FakeTracker(candidates=[candidate]), WorkspaceManager(config(root)), FakeRunner(), "Work", executor=executor)
            workspace = orchestrator.workspace_manager.create_for_issue(candidate.identifier)
            orchestrator.tick_once()
            self.assertTrue(executor.futures[0].set_running_or_notify_cancel())
            orchestrator.shutdown("operator")
            executor.futures[0].set_result(None)
            self.assertTrue(workspace.path.exists())
            self.assertEqual(orchestrator.state.running, {})
            self.assertEqual(orchestrator.state.worker_futures, {})
            self.assertEqual(orchestrator.state.claimed, set())
            self.assertNotIn(candidate.id, orchestrator.state.retry_attempts)

    def test_snapshot_includes_spec_session_retry_totals_and_rate_limits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            orchestrator, _ = self.build(root, FakeTracker())
            started_at = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
            last_event_at = datetime(2026, 1, 1, 12, 1, tzinfo=timezone.utc)
            workspace = root / "ABC-16"
            running = issue("ABC-16", state="In Progress")
            orchestrator.state.running[running.id] = RunningEntry(
                issue=running,
                started_at=started_at,
                workspace_path=workspace,
                session_id="thread-1-turn-2",
                thread_id="thread-1",
                turn_id="turn-2",
                codex_app_server_pid="12345",
                last_codex_event="turn.completed",
                last_codex_timestamp=last_event_at,
                last_codex_message="done",
                codex_input_tokens=10,
                codex_output_tokens=20,
                codex_total_tokens=30,
                last_reported_input_tokens=7,
                last_reported_output_tokens=8,
                last_reported_total_tokens=15,
                turn_count=2,
            )
            orchestrator.state.retry_attempts["abc-17"] = RetryEntry(
                issue_id="abc-17",
                identifier="ABC-17",
                attempt=3,
                due_at_ms=123456,
                error="transient failure",
            )
            orchestrator.state.codex_totals = {
                "input_tokens": 100,
                "output_tokens": 200,
                "total_tokens": 300,
                "seconds_running": 42.5,
            }
            orchestrator.state.codex_rate_limits = {"primary": {"remaining": 12, "reset_at": "2026-01-01T12:05:00+00:00"}}

            snapshot = orchestrator.snapshot(now=started_at + timedelta(seconds=10))

            self.assertEqual(snapshot["counts"], {"running": 1, "retrying": 1})
            self.assertEqual(snapshot["codex_totals"]["seconds_running"], 52.5)
            self.assertEqual(snapshot["rate_limits"]["primary"]["remaining"], 12)
            self.assertEqual(
                snapshot["retrying"],
                [
                    {
                        "issue_id": "abc-17",
                        "identifier": "ABC-17",
                        "attempt": 3,
                        "due_at_ms": 123456,
                        "error": "transient failure",
                    }
                ],
            )
            self.assertEqual(len(snapshot["running"]), 1)
            row = snapshot["running"][0]
            self.assertEqual(row["issue_id"], "abc-16")
            self.assertEqual(row["issue_identifier"], "ABC-16")
            self.assertEqual(row["state"], "In Progress")
            self.assertEqual(row["workspace_path"], str(workspace))
            self.assertEqual(row["session_id"], "thread-1-turn-2")
            self.assertEqual(row["thread_id"], "thread-1")
            self.assertEqual(row["turn_id"], "turn-2")
            self.assertEqual(row["codex_app_server_pid"], "12345")
            self.assertEqual(row["turn_count"], 2)
            self.assertEqual(row["last_event"], "turn.completed")
            self.assertEqual(row["last_codex_event"], "turn.completed")
            self.assertEqual(row["last_codex_timestamp"], last_event_at.isoformat())
            self.assertEqual(row["last_message"], "done")
            self.assertEqual(row["last_codex_message"], "done")
            self.assertEqual(row["codex_input_tokens"], 10)
            self.assertEqual(row["codex_output_tokens"], 20)
            self.assertEqual(row["codex_total_tokens"], 30)
            self.assertEqual(row["last_reported_input_tokens"], 7)
            self.assertEqual(row["last_reported_output_tokens"], 8)
            self.assertEqual(row["last_reported_total_tokens"], 15)
            self.assertEqual(row["started_at"], started_at.isoformat())

    def test_snapshot_is_stable_when_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            orchestrator, _ = self.build(Path(directory), FakeTracker())

            snapshot = orchestrator.snapshot()

            self.assertEqual(snapshot["counts"], {"running": 0, "retrying": 0})
            self.assertEqual(snapshot["running"], [])
            self.assertEqual(snapshot["retrying"], [])
            self.assertEqual(
                snapshot["codex_totals"],
                {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "seconds_running": 0.0},
            )
            self.assertIsNone(snapshot["rate_limits"])

    def test_finished_attempt_adds_runtime_seconds_to_totals(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = issue("ABC-32")
            orchestrator, _ = self.build(root, FakeTracker())
            orchestrator.state.running[candidate.id] = RunningEntry(
                issue=candidate,
                started_at=datetime.now(timezone.utc) - timedelta(seconds=2),
                workspace_path=root / "ABC-32",
            )

            orchestrator.finish_issue(candidate.id, normal=True, error=None)

            self.assertGreaterEqual(orchestrator.state.codex_totals["seconds_running"], 1.5)

    def test_session_lifecycle_logs_include_session_id_when_known(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = issue("ABC-33")
            cfg = config(root)
            runner = EventRunner([{"event": "session_started", "session_id": "thread-1-turn-1"}])
            logger = logging.getLogger("harness.runtime.test.session_id")
            orchestrator = Orchestrator(cfg, FakeTracker(candidates=[candidate]), WorkspaceManager(cfg), runner, "Work", executor=InlineExecutor(), logger=logger)

            with self.assertLogs(logger, level="INFO") as captured:
                orchestrator.tick_once()

            self.assertIn("session_id=thread-1-turn-1", "\n".join(captured.output))

    def test_agent_event_updates_live_session_tokens_and_rate_limits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            orchestrator, _ = self.build(root, FakeTracker())
            running = issue("ABC-28", state="In Progress")
            started_at = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
            orchestrator.state.running[running.id] = RunningEntry(issue=running, started_at=started_at)

            orchestrator.record_agent_event(
                running.id,
                {
                    "event": "thread/tokenUsage/updated",
                    "timestamp": "2026-01-01T12:01:00Z",
                    "session_id": "thread-1-turn-1",
                    "thread_id": "thread-1",
                    "turn_id": "turn-1",
                    "codex_app_server_pid": 12345,
                    "message": "tokens updated",
                    "usage": {"inputTokens": "10", "outputTokens": 5, "totalTokens": 15},
                    "rate_limits": {"primary": {"remaining": 12}},
                },
            )

            entry = orchestrator.state.running[running.id]
            self.assertEqual(entry.session_id, "thread-1-turn-1")
            self.assertEqual(entry.thread_id, "thread-1")
            self.assertEqual(entry.turn_id, "turn-1")
            self.assertEqual(entry.codex_app_server_pid, "12345")
            self.assertEqual(entry.last_codex_event, "thread/tokenUsage/updated")
            self.assertEqual(entry.last_codex_timestamp, datetime(2026, 1, 1, 12, 1, tzinfo=timezone.utc))
            self.assertEqual(entry.last_codex_message, "tokens updated")
            self.assertEqual(entry.codex_input_tokens, 10)
            self.assertEqual(entry.codex_output_tokens, 5)
            self.assertEqual(entry.codex_total_tokens, 15)
            self.assertEqual(entry.last_reported_input_tokens, 10)
            self.assertEqual(entry.last_reported_output_tokens, 5)
            self.assertEqual(entry.last_reported_total_tokens, 15)
            self.assertEqual(orchestrator.state.codex_totals["input_tokens"], 10)
            self.assertEqual(orchestrator.state.codex_totals["output_tokens"], 5)
            self.assertEqual(orchestrator.state.codex_totals["total_tokens"], 15)
            self.assertEqual(orchestrator.state.codex_rate_limits, {"primary": {"remaining": 12}})

    def test_agent_event_uses_absolute_token_deltas_and_ignores_delta_usage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            orchestrator, _ = self.build(root, FakeTracker())
            running = issue("ABC-29", state="In Progress")
            orchestrator.state.running[running.id] = RunningEntry(issue=running, started_at=datetime.now(timezone.utc))

            orchestrator.record_agent_event(
                running.id,
                {"event": "thread/tokenUsage/updated", "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}},
            )
            orchestrator.record_agent_event(
                running.id,
                {"event": "thread/tokenUsage/updated", "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}},
            )
            orchestrator.record_agent_event(
                running.id,
                {"event": "token_count", "payload": {"total_token_usage": {"input_tokens": 14, "output_tokens": 7, "total_tokens": 21}}},
            )
            orchestrator.record_agent_event(
                running.id,
                {"event": "notification", "usage": {"input_tokens": 999, "output_tokens": 999, "total_tokens": 1998}, "last_token_usage": {"total_tokens": 2000}},
            )

            entry = orchestrator.state.running[running.id]
            self.assertEqual(entry.codex_input_tokens, 14)
            self.assertEqual(entry.codex_output_tokens, 7)
            self.assertEqual(entry.codex_total_tokens, 21)
            self.assertEqual(orchestrator.state.codex_totals["input_tokens"], 14)
            self.assertEqual(orchestrator.state.codex_totals["output_tokens"], 7)
            self.assertEqual(orchestrator.state.codex_totals["total_tokens"], 21)

    def test_run_turn_result_events_are_aggregated_before_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = issue("ABC-30", state="Todo")
            cfg = config(root)
            runner = EventRunner(
                [
                    {
                        "event": "thread/tokenUsage/updated",
                        "payload": {"usage": {"input_tokens": 3, "output_tokens": 4}},
                    },
                    {
                        "event": "turn_completed",
                        "payload": {
                            "total_token_usage": {"inputTokens": 8, "outputTokens": 6, "totalTokens": 14},
                            "rateLimits": {"secondary": {"remaining": 3}},
                        },
                    },
                ]
            )
            orchestrator = Orchestrator(cfg, FakeTracker(candidates=[candidate]), WorkspaceManager(cfg), runner, "Work", executor=InlineExecutor())

            orchestrator.tick_once()

            self.assertEqual(orchestrator.state.codex_totals["input_tokens"], 8)
            self.assertEqual(orchestrator.state.codex_totals["output_tokens"], 6)
            self.assertEqual(orchestrator.state.codex_totals["total_tokens"], 14)
            self.assertEqual(orchestrator.state.codex_rate_limits, {"secondary": {"remaining": 3}})
            self.assertIn(candidate.id, orchestrator.state.last_attempts)
            self.assertEqual(orchestrator.state.last_attempts[candidate.id].status, "succeeded")
