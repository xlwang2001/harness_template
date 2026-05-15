import tempfile
import unittest
from pathlib import Path

from harness.runtime.models import RuntimeConfig
from harness.runtime.workspace import WorkspaceError, WorkspaceManager, ensure_contained, sanitize_workspace_key


def config(root: Path, *, hooks=None, hooks_timeout_ms=1000) -> RuntimeConfig:
    return RuntimeConfig(
        workflow_path=root / "WORKFLOW.md",
        tracker_kind="linear",
        tracker_endpoint="https://api.linear.app/graphql",
        tracker_api_key="token",
        tracker_project_slug="project",
        tracker_handoff_state=None,
        active_states=("Todo", "In Progress"),
        terminal_states=("Done",),
        polling_interval_ms=30000,
        workspace_root=root,
        hooks=hooks or {"after_create": None, "before_run": None, "after_run": None, "before_remove": None},
        hooks_timeout_ms=hooks_timeout_ms,
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

    def test_existing_non_directory_workspace_path_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            existing_file = root / "ABC-123"
            existing_file.write_text("not a directory", encoding="utf-8")
            manager = WorkspaceManager(config(root))
            with self.assertRaises(WorkspaceError):
                manager.create_for_issue("ABC-123")
            self.assertTrue(existing_file.is_file())

    def test_after_create_hook_runs_for_new_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            hooks = {"after_create": "printf ok > after_create.txt", "before_run": None, "after_run": None, "before_remove": None}
            manager = WorkspaceManager(config(root, hooks=hooks))
            workspace = manager.create_for_issue("ABC-123")
            self.assertEqual((workspace.path / "after_create.txt").read_text(encoding="utf-8"), "ok")

    def test_after_create_hook_timeout_is_fatal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            hooks = {"after_create": "sleep 1", "before_run": None, "after_run": None, "before_remove": None}
            manager = WorkspaceManager(config(root, hooks=hooks, hooks_timeout_ms=1))
            with self.assertRaises(WorkspaceError):
                manager.create_for_issue("ABC-123")

    def test_before_run_hook_timeout_is_fatal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            hooks = {"after_create": None, "before_run": "sleep 1", "after_run": None, "before_remove": None}
            manager = WorkspaceManager(config(root, hooks=hooks, hooks_timeout_ms=1))
            workspace = manager.create_for_issue("ABC-123")
            with self.assertRaises(WorkspaceError):
                manager.run_hook("before_run", workspace, fatal=True)

    def test_after_run_hook_timeout_is_nonfatal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            hooks = {"after_create": None, "before_run": None, "after_run": "sleep 1", "before_remove": None}
            manager = WorkspaceManager(config(root, hooks=hooks, hooks_timeout_ms=1))
            workspace = manager.create_for_issue("ABC-123")
            manager.run_hook("after_run", workspace, fatal=False)

    def test_before_remove_hook_timeout_is_nonfatal_and_workspace_is_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            hooks = {"after_create": None, "before_run": None, "after_run": None, "before_remove": "sleep 1"}
            manager = WorkspaceManager(config(root, hooks=hooks, hooks_timeout_ms=1))
            workspace = manager.create_for_issue("ABC-123")
            manager.cleanup_for_issue("ABC-123")
            self.assertFalse(workspace.path.exists())
