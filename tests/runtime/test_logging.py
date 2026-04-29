import logging
import tempfile
import unittest
from concurrent.futures import Future
from pathlib import Path

from harness.runtime.agent import AgentRunResult
from harness.runtime.models import Issue, RuntimeConfig
from harness.runtime.orchestrator import Orchestrator
from harness.runtime.runtime_logging import REDACTED, emit_runtime_log, redact_mapping
from harness.runtime.workspace import WorkspaceManager


SECRET = "linear-secret-token"


def config(root: Path) -> RuntimeConfig:
    return RuntimeConfig(
        workflow_path=root / "WORKFLOW.md",
        tracker_kind="linear",
        tracker_endpoint="https://api.linear.app/graphql",
        tracker_api_key=SECRET,
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
        codex_stall_timeout_ms=300000,
        approval_policy="on-request",
        thread_sandbox="workspace-write",
        turn_sandbox_policy="workspace-write",
    )


class InlineExecutor:
    def submit(self, fn, /, *args, **kwargs):
        future = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except Exception as exc:
            future.set_exception(exc)
        return future


class FakeTracker:
    def __init__(self, candidates):
        self.candidates = candidates

    def fetch_candidate_issues(self):
        return list(self.candidates)

    def fetch_issue_states_by_ids(self, issue_ids):
        return []

    def fetch_issues_by_states(self, state_names):
        return []


class FakeRunner:
    def run_turn(self, issue, prompt, workspace_path, attempt=None):
        return AgentRunResult(success=True)


class RuntimeLoggingTests(unittest.TestCase):
    def test_emit_runtime_log_redacts_sensitive_keys_and_secret_values(self):
        logger = logging.getLogger("harness.runtime.test.redaction")
        with self.assertLogs(logger, level="INFO") as captured:
            emit_runtime_log(
                logger,
                "redaction_check",
                api_key=SECRET,
                message=f"value contains {SECRET}",
                secrets=(SECRET,),
            )
        output = "\n".join(captured.output)
        self.assertIn(f"api_key={REDACTED}", output)
        self.assertIn(f"message=value contains {REDACTED}", output)
        self.assertNotIn(SECRET, output)

    def test_redact_mapping_redacts_secret_fields(self):
        redacted = redact_mapping({"tracker_api_key": SECRET, "error": f"bad {SECRET}"}, secrets=(SECRET,))
        self.assertEqual(redacted["tracker_api_key"], REDACTED)
        self.assertEqual(redacted["error"], f"bad {REDACTED}")

    def test_orchestrator_emits_structured_lifecycle_logs_without_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cfg = config(root)
            issue = Issue(id="abc-1", identifier="ABC-1", title="Title", state="Todo")
            logger = logging.getLogger("harness.runtime.test.lifecycle")
            orchestrator = Orchestrator(
                cfg,
                FakeTracker([issue]),
                WorkspaceManager(cfg, logger=logger),
                FakeRunner(),
                "Work on {{ issue.identifier }}",
                executor=InlineExecutor(),
                logger=logger,
            )
            with self.assertLogs(logger, level="INFO") as captured:
                orchestrator.tick_once()
            output = "\n".join(captured.output)
            for event in (
                "event=tick_started",
                "event=dispatch_started",
                "event=workspace_prepared",
                "event=agent_session_started",
                "event=agent_session_completed",
                "event=worker_completed",
                "event=retry_scheduled",
            ):
                self.assertIn(event, output)
            self.assertNotIn(SECRET, output)
