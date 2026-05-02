import tempfile
import unittest
from pathlib import Path

from harness.runtime.models import BlockerRef, Issue, RuntimeConfig
from harness.runtime.preview import compute_dispatch_preview, format_dispatch_preview


def config(root: Path, **overrides) -> RuntimeConfig:
    values = {
        "workflow_path": root / "WORKFLOW.md",
        "tracker_kind": "linear",
        "tracker_endpoint": "https://api.linear.app/graphql",
        "tracker_api_key": "token",
        "tracker_project_slug": "project",
        "active_states": ("Todo", "In Progress"),
        "terminal_states": ("Done", "Cancelled"),
        "polling_interval_ms": 30000,
        "workspace_root": root / ".workspaces",
        "hooks": {"after_create": None, "before_run": None, "after_run": None, "before_remove": None},
        "hooks_timeout_ms": 1000,
        "max_concurrent_agents": 2,
        "max_turns": 20,
        "max_retry_backoff_ms": 300000,
        "max_concurrent_agents_by_state": {},
        "codex_command": "true",
        "codex_turn_timeout_ms": 1000,
        "codex_read_timeout_ms": 1000,
        "codex_stall_timeout_ms": 300000,
        "approval_policy": "on-request",
        "thread_sandbox": "workspace-write",
        "turn_sandbox_policy": "workspace-write",
    }
    values.update(overrides)
    return RuntimeConfig(**values)


def issue(identifier: str, **overrides) -> Issue:
    values = {
        "id": identifier.lower(),
        "identifier": identifier,
        "title": f"{identifier} title",
        "state": "Todo",
        "priority": None,
        "blocked_by": (),
    }
    values.update(overrides)
    return Issue(**values)


class DispatchPreviewTests(unittest.TestCase):
    def test_preview_sorts_candidates_and_does_not_create_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cfg = config(root)
            preview = compute_dispatch_preview(
                cfg,
                "Work on {{ issue.identifier }}",
                [issue("ABC-2", priority=2), issue("ABC-1", priority=1)],
            )

            self.assertEqual([candidate.issue.identifier for candidate in preview.candidates], ["ABC-1", "ABC-2"])
            self.assertTrue(all(candidate.eligible for candidate in preview.candidates))
            self.assertEqual(preview.candidates[0].workspace_path, root / ".workspaces" / "ABC-1")
            self.assertIn("Work on ABC-1", preview.candidates[0].prompt_preview)
            self.assertFalse((root / ".workspaces").exists())

    def test_preview_reports_blockers_and_concurrency_reasons(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cfg = config(root, max_concurrent_agents=1)
            blocked = issue("ABC-2", blocked_by=(BlockerRef(identifier="ABC-0", state="In Progress"),))
            overflow = issue("ABC-3", priority=3)
            preview = compute_dispatch_preview(cfg, "Work", [issue("ABC-1", priority=1), blocked, overflow])

            reasons = {candidate.issue.identifier: candidate.reason for candidate in preview.candidates}
            self.assertEqual(reasons["ABC-1"], "eligible")
            self.assertEqual(reasons["ABC-2"], "blocked_by non-terminal issue ABC-0")
            self.assertEqual(reasons["ABC-3"], "global_concurrency_exhausted")

    def test_preview_reports_prompt_render_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            preview = compute_dispatch_preview(config(root), "Work {{ missing.value }}", [issue("ABC-1")])

            self.assertTrue(preview.has_errors)
            self.assertFalse(preview.candidates[0].eligible)
            self.assertEqual(preview.candidates[0].reason, "prompt_render_failed")
            self.assertIn("unknown template variable", preview.candidates[0].prompt_error)

    def test_format_preview_is_operator_readable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            preview = compute_dispatch_preview(config(root), "Work on {{ issue.identifier }}", [issue("ABC-1")])

            output = format_dispatch_preview(preview)

            self.assertIn("Dispatch preview for", output)
            self.assertIn("project_slug: project", output)
            self.assertIn("ABC-1 - ABC-1 title", output)
            self.assertIn("eligible: yes", output)
            self.assertIn("prompt: Work on ABC-1", output)


if __name__ == "__main__":
    unittest.main()
