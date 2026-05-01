import os
import tempfile
import textwrap
import unittest
from pathlib import Path

from harness.runtime.agent import CodexAgentRunner
from harness.runtime.models import Issue, RuntimeConfig
from harness.runtime.tracker import LinearClient
from harness.runtime.workflow import load_workflow, resolve_config, validate_dispatch_config


def _integration_enabled() -> bool:
    return os.environ.get("HARNESS_RUN_INTEGRATION") == "1"


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

    def _temporary_workspace_root(self):
        base = os.environ.get("HARNESS_INTEGRATION_WORKSPACE_ROOT")
        if not base:
            return tempfile.TemporaryDirectory()
        root = Path(base).expanduser()
        root.mkdir(parents=True, exist_ok=True)
        return tempfile.TemporaryDirectory(dir=root)


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
