import tempfile
import unittest
from pathlib import Path

from harness.runtime.models import RuntimeConfig
from harness.runtime.workspace import WorkspaceError, WorkspaceManager, ensure_contained, sanitize_workspace_key


def config(root: Path) -> RuntimeConfig:
    return RuntimeConfig(
        workflow_path=root / "WORKFLOW.md",
        tracker_kind="linear",
        tracker_endpoint="https://api.linear.app/graphql",
        tracker_api_key="token",
        tracker_project_slug="project",
        active_states=("Todo", "In Progress"),
        terminal_states=("Done",),
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


class WorkspaceTests(unittest.TestCase):
    def test_sanitizes_identifier(self):
        self.assertEqual(sanitize_workspace_key("ABC-123 unsafe/name"), "ABC-123_unsafe_name")

    def test_create_reuses_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = WorkspaceManager(config(Path(directory)))
            first = manager.create_for_issue("ABC-123")
            second = manager.create_for_issue("ABC-123")
            self.assertTrue(first.created_now)
            self.assertFalse(second.created_now)
            self.assertEqual(first.path, second.path)

    def test_containment_rejects_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(WorkspaceError):
                ensure_contained(root, root.parent)
