import tempfile
import unittest
import os
import sys
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

import harness.cli as cli_module
from harness.cli import main
from harness.runtime.models import Issue, RuntimeConfig
from harness.runtime.preview import DispatchPreview, CandidatePreview
from harness.workflow_validator import validate_workflow


def run_cli(args):
    stdout = StringIO()
    stderr = StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        code = main(args)
    return code, stdout.getvalue(), stderr.getvalue()


class CliTests(unittest.TestCase):
    def test_init_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            code, _, _ = run_cli(["init", "--target", str(tmp_path), "--profile", "toy-example"])
            self.assertEqual(code, 0)
            code, _, stderr = run_cli(["init", "--target", str(tmp_path), "--profile", "toy-example"])
            self.assertEqual(code, 2)
            self.assertIn("refusing to overwrite", stderr)

    def test_init_dry_run_does_not_write(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            code, _, _ = run_cli(["init", "--target", str(tmp_path), "--profile", "toy-example", "--dry-run"])
            self.assertEqual(code, 0)
            self.assertFalse((tmp_path / "AGENTS.md").exists())

    def test_init_force_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            code, _, _ = run_cli(["init", "--target", str(tmp_path), "--profile", "toy-example"])
            self.assertEqual(code, 0)
            (tmp_path / "AGENTS.md").write_text("changed", encoding="utf-8")
            code, _, _ = run_cli(["init", "--target", str(tmp_path), "--profile", "toy-example", "--force"])
            self.assertEqual(code, 0)
            self.assertIn("docs/README.md", (tmp_path / "AGENTS.md").read_text(encoding="utf-8"))

    def test_validate_generated_repo_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            code, _, _ = run_cli(["init", "--target", str(tmp_path), "--profile", "toy-example"])
            self.assertEqual(code, 0)
            code, _, _ = run_cli(["validate", "--target", str(tmp_path)])
            self.assertEqual(code, 0)

    def test_validate_reports_missing_docs(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            (tmp_path / "WORKFLOW.md").write_text("---\ntracker:\nworkspace:\nagent:\ncodex:\n---\n", encoding="utf-8")
            code, _, _ = run_cli(["validate", "--target", str(tmp_path)])
            self.assertEqual(code, 1)

    def test_validate_reports_malformed_workflow(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            code, _, _ = run_cli(["init", "--target", str(tmp_path), "--profile", "toy-example"])
            self.assertEqual(code, 0)
            (tmp_path / "WORKFLOW.md").write_text("not front matter", encoding="utf-8")
            code, _, _ = run_cli(["validate", "--target", str(tmp_path)])
            self.assertEqual(code, 1)

    def test_workflow_validator_warns_on_unsupported_yaml_constructs(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            (tmp_path / "WORKFLOW.md").write_text(
                """---
tracker:
  kind: linear
  api_key: &linear_key "$LINEAR_API_KEY"
  project_slug: *linear_key
  active_states:
    - Todo
  terminal_states:
    - Done
workspace:
  root: ./workspaces
agent:
  max_concurrent_agents: 1
codex:
  command: >
    codex app-server
  approval_policy: !policy on-request
<<: {}
---
Work on {{ issue.identifier }}.
Title: {{ issue.title }}
Description: {{ issue.description }}
""",
                encoding="utf-8",
            )

            messages = validate_workflow(tmp_path)

            warnings = [message.message for message in messages if message.level == "WARNING"]
            errors = [message.message for message in messages if message.level == "ERROR"]
            self.assertEqual(errors, [])
            for expected in (
                "YAML anchors",
                "YAML aliases",
                "YAML merge keys",
                "YAML custom tags",
                "YAML folded block scalars",
            ):
                self.assertTrue(any(expected in warning for warning in warnings), warnings)

    def test_run_reports_missing_workflow(self):
        with tempfile.TemporaryDirectory() as directory:
            code, _, stderr = run_cli(["run", str(Path(directory) / "missing.md")])
            self.assertEqual(code, 2)
            self.assertIn("workflow file not found", stderr)

    def test_run_reports_startup_validation_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            workflow = Path(directory) / "WORKFLOW.md"
            workflow.write_text(
                """---
tracker:
  kind: linear
  project_slug: project
codex:
  command: "true"
---
Work on {{ issue.identifier }}
""",
                encoding="utf-8",
            )
            old_key = os.environ.pop("LINEAR_API_KEY", None)
            try:
                code, _, stderr = run_cli(["run", str(workflow)])
            finally:
                if old_key is not None:
                    os.environ["LINEAR_API_KEY"] = old_key
            self.assertEqual(code, 1)
            self.assertIn("runtime startup failed", stderr)

    def test_run_passes_port_override_to_runtime_service(self):
        with tempfile.TemporaryDirectory() as directory:
            workflow = Path(directory) / "WORKFLOW.md"
            workflow.write_text("Work on {{ issue.identifier }}", encoding="utf-8")
            calls = []

            class FakeRuntimeService:
                def __init__(self, workflow_path, *, server_port_override=None):
                    calls.append((workflow_path, server_port_override))

                def run_forever(self):
                    return 0

            original = cli_module.RuntimeService
            try:
                cli_module.RuntimeService = FakeRuntimeService
                code, _, _ = run_cli(["run", "--port", "0", str(workflow)])
            finally:
                cli_module.RuntimeService = original

            self.assertEqual(code, 0)
            self.assertEqual(calls, [(workflow.resolve(), 0)])

    def test_run_rejects_negative_port(self):
        with self.assertRaises(SystemExit):
            run_cli(["run", "--port", "-1"])

    def test_dispatch_preview_prints_read_only_preview(self):
        with tempfile.TemporaryDirectory() as directory:
            workflow = Path(directory) / "WORKFLOW.md"
            workflow.write_text("Work", encoding="utf-8")
            calls = []

            def fake_build(workflow_path, *, limit):
                calls.append((workflow_path, limit))
                cfg = RuntimeConfig(
                    workflow_path=workflow_path,
                    tracker_kind="linear",
                    tracker_endpoint="https://api.linear.app/graphql",
                    tracker_api_key="token",
                    tracker_project_slug="project",
                    active_states=("Todo",),
                    terminal_states=("Done",),
                    polling_interval_ms=30000,
                    workspace_root=Path(directory) / ".workspaces",
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
                issue = Issue(id="abc-1", identifier="ABC-1", title="Preview issue", state="Todo")
                return DispatchPreview(
                    workflow_path=workflow_path,
                    config=cfg,
                    candidates=[
                        CandidatePreview(
                            issue=issue,
                            eligible=True,
                            reason="eligible",
                            workspace_path=cfg.workspace_root / "ABC-1",
                            prompt_preview="Work on ABC-1",
                            prompt_error=None,
                        )
                    ],
                )

            original = cli_module.build_dispatch_preview
            try:
                cli_module.build_dispatch_preview = fake_build
                code, stdout, stderr = run_cli(["dispatch-preview", "--workflow", str(workflow), "--limit", "5"])
            finally:
                cli_module.build_dispatch_preview = original

            self.assertEqual(code, 0)
            self.assertEqual(stderr, "")
            self.assertEqual(calls, [(workflow.resolve(), 5)])
            self.assertIn("ABC-1 - Preview issue", stdout)
            self.assertIn("eligible: yes", stdout)

    def test_dispatch_preview_reports_missing_workflow(self):
        with tempfile.TemporaryDirectory() as directory:
            code, _, stderr = run_cli(["dispatch-preview", "--workflow", str(Path(directory) / "missing.md")])
            self.assertEqual(code, 2)
            self.assertIn("workflow file not found", stderr)

    def test_dispatch_preview_rejects_non_positive_limit(self):
        with self.assertRaises(SystemExit):
            run_cli(["dispatch-preview", "--workflow", "WORKFLOW.md", "--limit", "0"])

    def test_validate_review_packet_accepts_markdown_packet(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "review-packet.md"
            path.write_text(
                """# Review Packet: ABC-1

## Issue
## Pull Request
## Summary
## Changed files
## Tests run
## CI status
## Known risks
## Human review checklist
""",
                encoding="utf-8",
            )

            code, stdout, stderr = run_cli(["validate-review-packet", "--path", str(path)])

            self.assertEqual(code, 0)
            self.assertIn("review packet validation passed", stdout)
            self.assertEqual(stderr, "")

    def test_validate_review_packet_reports_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "review-packet.md"
            path.write_text("# Review Packet\n", encoding="utf-8")

            code, stdout, stderr = run_cli(["validate-review-packet", "--path", str(path)])

            self.assertEqual(code, 1)
            self.assertIn("missing section", stdout)
            self.assertIn("review packet validation failed", stderr)

    def test_runtime_check_runs_runtime_unittest_discovery(self):
        calls = []

        def fake_run(command):
            calls.append(command)
            return type("Completed", (), {"returncode": 0})()

        original = cli_module.subprocess.run
        try:
            cli_module.subprocess.run = fake_run
            code, _, _ = run_cli(["runtime-check"])
        finally:
            cli_module.subprocess.run = original

        self.assertEqual(code, 0)
        self.assertEqual(calls, [[sys.executable, "-m", "unittest", "discover", "-s", "tests/runtime"]])

    def test_runtime_check_returns_subprocess_failure_code(self):
        def fake_run(command):
            return type("Completed", (), {"returncode": 7})()

        original = cli_module.subprocess.run
        try:
            cli_module.subprocess.run = fake_run
            code, _, _ = run_cli(["runtime-check"])
        finally:
            cli_module.subprocess.run = original

        self.assertEqual(code, 7)
