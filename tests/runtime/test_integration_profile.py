import os
import tempfile
import textwrap
import unittest
from contextlib import contextmanager
from concurrent.futures import Future
from pathlib import Path

import harness.runtime.service as service_module
from harness.runtime.agent import CodexAgentRunner
from harness.runtime.orchestrator import Orchestrator
from harness.runtime.models import Issue, RuntimeConfig
from harness.runtime.service import RuntimeService
from harness.runtime.tracker import LinearClient
from harness.runtime.workflow import load_workflow, resolve_config, validate_dispatch_config
from harness.runtime.workspace import WorkspaceManager


def _integration_enabled() -> bool:
    return os.environ.get("HARNESS_RUN_INTEGRATION") == "1"


def _linear_mutation_integration_enabled() -> bool:
    return os.environ.get("HARNESS_RUN_LINEAR_MUTATION_INTEGRATION") == "1"


class RealIntegrationProfileTests(unittest.TestCase):
    def setUp(self):
        if not _integration_enabled():
            self.skipTest("set HARNESS_RUN_INTEGRATION=1 to run real integration checks")

    def test_linear_smoke_fetches_candidates_read_only(self):
        self._require_env("LINEAR_API_KEY")
        self._require_env("LINEAR_PROJECT_SLUG")
        with self._temporary_workspace_root() as root:
            workflow_path = root / "WORKFLOW.md"
            workflow_path.write_text(
                textwrap.dedent(
                    """\
                    ---
                    tracker:
                      kind: linear
                      api_key: $LINEAR_API_KEY
                      project_slug: $LINEAR_PROJECT_SLUG
                    workspace:
                      root: ".workspaces"
                    codex:
                      command: "true"
                    ---
                    Work on {{ issue.identifier }}.
                    """
                ),
                encoding="utf-8",
            )
            config = resolve_config(load_workflow(workflow_path))
            validate_dispatch_config(config)

            issues = LinearClient(config).fetch_candidate_issues()

        self.assertIsInstance(issues, list)
        for issue in issues:
            self.assertIsInstance(issue, Issue)
            self.assertTrue(issue.id)
            self.assertTrue(issue.identifier)

    def test_linear_smoke_fetches_terminal_states_read_only(self):
        self._require_env("LINEAR_API_KEY")
        self._require_env("LINEAR_PROJECT_SLUG")
        with self._temporary_workspace_root() as root:
            workflow_path = root / "WORKFLOW.md"
            workflow_path.write_text(
                textwrap.dedent(
                    """\
                    ---
                    tracker:
                      kind: linear
                      api_key: $LINEAR_API_KEY
                      project_slug: $LINEAR_PROJECT_SLUG
                      terminal_states: ["Done", "Cancelled", "Canceled"]
                    workspace:
                      root: ".workspaces"
                    codex:
                      command: "true"
                    ---
                    Work on {{ issue.identifier }}.
                    """
                ),
                encoding="utf-8",
            )
            config = resolve_config(load_workflow(workflow_path))
            validate_dispatch_config(config)

            issues = LinearClient(config).fetch_issues_by_states(config.terminal_states)

        self.assertIsInstance(issues, list)
        for issue in issues:
            self.assertIsInstance(issue, Issue)
            self.assertTrue(issue.id)
            self.assertTrue(issue.identifier)

    def test_service_loop_smoke_cleans_terminal_and_reuses_preserved_workspace(self):
        with self._temporary_workspace_root() as root:
            active = Issue(id="active-1", identifier="INT/1", title="Active integration", state="Todo")
            terminal = Issue(id="done-1", identifier="DONE/1", title="Done integration", state="Done")
            active_workspace = root / "INT_1"
            active_workspace.mkdir(parents=True)
            marker = active_workspace / "preserved.txt"
            marker.write_text("operator work", encoding="utf-8")
            terminal_workspace = root / "DONE_1"
            terminal_workspace.mkdir(parents=True)

            cfg = _runtime_config(root, "true")
            tracker = IntegrationFakeTracker(candidates=[active], terminal=[terminal])
            runner = IntegrationFakeRunner()
            service = IntegrationFakeService(cfg, tracker, runner)

            code = _run_service_without_basic_config(service)

            self.assertEqual(code, 0)
            self.assertEqual(tracker.terminal_fetches, 1)
            self.assertEqual(tracker.candidate_fetches, 1)
            self.assertTrue(marker.exists())
            self.assertFalse(terminal_workspace.exists())
            self.assertEqual(runner.workspaces, [active_workspace])

            restarted = Orchestrator(
                cfg,
                tracker,
                WorkspaceManager(cfg),
                runner,
                "Work on {{ issue.identifier }}.",
                executor=InlineExecutor(),
            )
            self.assertFalse(restarted.state.running)
            self.assertFalse(restarted.state.retry_attempts)
            self.assertFalse(restarted.state.last_attempts)
            self.assertTrue(active_workspace.exists())

    def test_codex_app_server_smoke_when_command_is_configured(self):
        command = os.environ.get("HARNESS_INTEGRATION_CODEX_COMMAND")
        if not command:
            self.skipTest("set HARNESS_INTEGRATION_CODEX_COMMAND to run the Codex app-server smoke")
        with self._temporary_workspace_root() as root:
            workspace = root / "workspace"
            workspace.mkdir()
            runner = CodexAgentRunner(_runtime_config(root, command))

            result = runner.run_turn(
                Issue(id="integration-issue", identifier="INT-1", title="Integration smoke", state="Todo"),
                "Complete this integration smoke turn without editing files.",
                workspace,
                attempt=1,
            )

        self.assertTrue(result.success)
        self.assertTrue(result.session_id)

    def _require_env(self, name: str) -> str:
        value = os.environ.get(name)
        if not value:
            self.fail(f"{name} is required when HARNESS_RUN_INTEGRATION=1")
        return value

    @contextmanager
    def _temporary_workspace_root(self):
        base = os.environ.get("HARNESS_INTEGRATION_WORKSPACE_ROOT")
        parent = Path(base).expanduser() if base else None
        if parent is not None:
            parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as directory:
            yield Path(directory)


class LinearMutationIntegrationProfilePlaceholderTests(unittest.TestCase):
    def test_linear_mutation_profile_is_separately_gated_and_placeholder_only(self):
        if not _linear_mutation_integration_enabled():
            self.skipTest("set HARNESS_RUN_LINEAR_MUTATION_INTEGRATION=1 to evaluate the reserved Linear mutation profile")
        required = [
            "LINEAR_API_KEY",
            "HARNESS_LINEAR_MUTATION_ISSUE_ID",
            "HARNESS_LINEAR_MUTATION_TARGET_STATE",
            "HARNESS_LINEAR_MUTATION_COMMENT_BODY",
        ]
        missing = [name for name in required if not os.environ.get(name)]
        if missing:
            self.fail(
                "Linear mutation integration is explicitly gated and requires target variables before any future write check can run: "
                + ", ".join(missing)
            )
        self.skipTest("Linear mutation smoke is reserved but not implemented until project-specific cleanup and rollback policy exists")


class IntegrationFakeTracker:
    def __init__(self, *, candidates=None, terminal=None):
        self.candidates = list(candidates or [])
        self.terminal = list(terminal or [])
        self.candidate_fetches = 0
        self.terminal_fetches = 0
        self.state_fetches = 0

    def fetch_candidate_issues(self):
        self.candidate_fetches += 1
        return list(self.candidates)

    def fetch_issues_by_states(self, state_names):
        self.terminal_fetches += 1
        return [issue for issue in self.terminal if issue.state in state_names]

    def fetch_issue_states_by_ids(self, issue_ids):
        self.state_fetches += 1
        return [issue for issue in self.candidates if issue.id in issue_ids]


class IntegrationFakeRunner:
    def __init__(self):
        self.workspaces = []

    def run_turn(self, issue, prompt, workspace_path, attempt=None, on_event=None):
        self.workspaces.append(workspace_path)
        if on_event is not None:
            on_event({"event": "session_started", "session_id": "integration-session"})
            on_event({"event": "turn_completed", "session_id": "integration-session"})
        return type("Result", (), {"success": True, "events": (), "session_id": "integration-session"})()


class InlineExecutor:
    def submit(self, fn, /, *args, **kwargs):
        future = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except Exception as exc:
            future.set_exception(exc)
        return future

    def shutdown(self, **kwargs):
        return None


class OneTickOrchestrator(Orchestrator):
    def tick_once(self):
        super().tick_once()
        raise KeyboardInterrupt()


class IntegrationFakeService(RuntimeService):
    def __init__(self, cfg, tracker, runner):
        super().__init__(None)
        self.cfg = cfg
        self.tracker = tracker
        self.runner = runner

    def build_orchestrator(self):
        return OneTickOrchestrator(
            self.cfg,
            self.tracker,
            WorkspaceManager(self.cfg),
            self.runner,
            "Work on {{ issue.identifier }}.",
            executor=InlineExecutor(),
        )


def _run_service_without_basic_config(service):
    original_basic_config = service_module.logging.basicConfig
    service_module.logging.basicConfig = lambda *args, **kwargs: None
    try:
        return service.run_forever()
    finally:
        service_module.logging.basicConfig = original_basic_config


def _runtime_config(root: Path, command: str) -> RuntimeConfig:
    return RuntimeConfig(
        workflow_path=root / "WORKFLOW.md",
        tracker_kind="linear",
        tracker_endpoint="https://api.linear.app/graphql",
        tracker_api_key=os.environ.get("LINEAR_API_KEY") or "integration-placeholder",
        tracker_project_slug=os.environ.get("LINEAR_PROJECT_SLUG") or "integration-placeholder",
        active_states=("Todo", "In Progress"),
        terminal_states=("Done", "Cancelled", "Canceled"),
        polling_interval_ms=30000,
        workspace_root=root,
        hooks={"after_create": None, "before_run": None, "after_run": None, "before_remove": None},
        hooks_timeout_ms=60000,
        max_concurrent_agents=1,
        max_turns=1,
        max_retry_backoff_ms=300000,
        max_concurrent_agents_by_state={},
        codex_command=command,
        codex_turn_timeout_ms=180000,
        codex_read_timeout_ms=30000,
        codex_stall_timeout_ms=300000,
        approval_policy="on-request",
        thread_sandbox="workspace-write",
        turn_sandbox_policy="workspace-write",
    )


if __name__ == "__main__":
    unittest.main()
