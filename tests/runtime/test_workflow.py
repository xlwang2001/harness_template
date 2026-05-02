import os
import tempfile
import unittest
from pathlib import Path

from harness.runtime.prompt import TemplateRenderError, render_prompt
from harness.runtime.models import Issue
from harness.runtime.workflow import ConfigValidationError, WorkflowParseError, WorkflowReloader, load_workflow, parse_simple_yaml, resolve_config, validate_dispatch_config


WORKFLOW = """---
tracker:
  kind: linear
  api_key: $LINEAR_API_KEY
  project_slug: "$LINEAR_PROJECT_SLUG"
workspace:
  root: ".workspaces"
agent:
  max_concurrent_agents: 2
codex:
  command: "true"
---
Issue {{ issue.identifier }} attempt {{ attempt }}
"""


def workflow_text(*, interval=30000, concurrency=2, workspace_root=".workspaces", before_run=None, prompt="Issue {{ issue.identifier }}"):
    hook = f'\nhooks:\n  before_run: "{before_run}"' if before_run else ""
    return f"""---
tracker:
  kind: linear
  api_key: $LINEAR_API_KEY
  project_slug: "$LINEAR_PROJECT_SLUG"
polling:
  interval_ms: {interval}
workspace:
  root: "{workspace_root}"
agent:
  max_concurrent_agents: {concurrency}
codex:
  command: "true"{hook}
---
{prompt}
"""


class WorkflowTests(unittest.TestCase):
    def test_loads_front_matter_and_resolves_env(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "WORKFLOW.md"
            path.write_text(WORKFLOW, encoding="utf-8")
            os.environ["LINEAR_API_KEY"] = "token"
            os.environ["LINEAR_PROJECT_SLUG"] = "project"
            workflow = load_workflow(path)
            config = resolve_config(workflow)
            self.assertEqual(config.tracker_api_key, "token")
            self.assertEqual(config.tracker_project_slug, "project")
            self.assertEqual(config.max_concurrent_agents, 2)
            self.assertTrue(config.workspace_root.is_absolute())
            self.assertFalse(config.server_enabled)
            self.assertEqual(config.server_host, "127.0.0.1")
            self.assertEqual(config.server_port, 8765)
            self.assertEqual(config.logging_level, "INFO")
            self.assertTrue(config.logging_console)
            self.assertIsNone(config.logging_file)
            self.assertIsNone(config.runtime_state_file)
            self.assertFalse(config.runtime_state_persist_retries)
            self.assertFalse(config.runtime_state_persist_sessions)
            validate_dispatch_config(config)

    def test_logging_config_parses_level_console_and_relative_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "WORKFLOW.md"
            path.write_text(
                """---
tracker:
  kind: linear
  api_key: token
  project_slug: project
codex:
  command: "true"
logging:
  level: debug
  console: false
  file: "logs/runtime.log"
---
Issue {{ issue.identifier }}
""",
                encoding="utf-8",
            )
            config = resolve_config(load_workflow(path))
            self.assertEqual(config.logging_level, "DEBUG")
            self.assertFalse(config.logging_console)
            self.assertEqual(config.logging_file, Path(directory, "logs", "runtime.log").resolve())

    def test_invalid_logging_level_fails_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "WORKFLOW.md"
            path.write_text(
                """---
tracker:
  kind: linear
  api_key: token
  project_slug: project
logging:
  level: verbose
---
Issue {{ issue.identifier }}
""",
                encoding="utf-8",
            )
            with self.assertRaises(ConfigValidationError):
                resolve_config(load_workflow(path))

    def test_runtime_state_file_defaults_persistence_enabled(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "WORKFLOW.md"
            path.write_text(
                """---
tracker:
  kind: linear
  api_key: token
  project_slug: project
codex:
  command: "true"
runtime_state:
  file: ".harness/runtime-state.json"
---
Issue {{ issue.identifier }}
""",
                encoding="utf-8",
            )
            config = resolve_config(load_workflow(path))
            self.assertEqual(config.runtime_state_file, Path(directory, ".harness", "runtime-state.json").resolve())
            self.assertTrue(config.runtime_state_persist_retries)
            self.assertTrue(config.runtime_state_persist_sessions)

    def test_runtime_state_persistence_flags_can_be_disabled(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "WORKFLOW.md"
            path.write_text(
                """---
tracker:
  kind: linear
  api_key: token
  project_slug: project
codex:
  command: "true"
runtime_state:
  file: "runtime-state.json"
  persist_retries: false
  persist_sessions: false
---
Issue {{ issue.identifier }}
""",
                encoding="utf-8",
            )
            config = resolve_config(load_workflow(path))
            self.assertEqual(config.runtime_state_file, Path(directory, "runtime-state.json").resolve())
            self.assertFalse(config.runtime_state_persist_retries)
            self.assertFalse(config.runtime_state_persist_sessions)

    def test_server_config_parses_enabled_host_and_port(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "WORKFLOW.md"
            path.write_text(
                """---
tracker:
  kind: linear
  api_key: token
  project_slug: project
codex:
  command: "true"
server:
  enabled: true
  host: "127.0.0.1"
  port: 0
---
Issue {{ issue.identifier }}
""",
                encoding="utf-8",
            )
            config = resolve_config(load_workflow(path))
            self.assertTrue(config.server_enabled)
            self.assertEqual(config.server_host, "127.0.0.1")
            self.assertEqual(config.server_port, 0)

    def test_server_port_presence_enables_status_server(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "WORKFLOW.md"
            path.write_text(
                """---
tracker:
  kind: linear
  api_key: token
  project_slug: project
codex:
  command: "true"
server:
  port: 0
---
Issue {{ issue.identifier }}
""",
                encoding="utf-8",
            )
            config = resolve_config(load_workflow(path))
            self.assertTrue(config.server_enabled)
            self.assertEqual(config.server_port, 0)

    def test_server_enabled_without_port_uses_default_port(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "WORKFLOW.md"
            path.write_text(
                """---
tracker:
  kind: linear
  api_key: token
  project_slug: project
codex:
  command: "true"
server:
  enabled: true
---
Issue {{ issue.identifier }}
""",
                encoding="utf-8",
            )
            config = resolve_config(load_workflow(path))
            self.assertTrue(config.server_enabled)
            self.assertEqual(config.server_port, 8765)

    def test_negative_server_port_fails_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "WORKFLOW.md"
            path.write_text(
                """---
tracker:
  kind: linear
  api_key: token
  project_slug: project
server:
  port: -1
---
Issue {{ issue.identifier }}
""",
                encoding="utf-8",
            )
            with self.assertRaises(ConfigValidationError):
                resolve_config(load_workflow(path))

    def test_dispatch_validation_requires_env(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "WORKFLOW.md"
            path.write_text(WORKFLOW, encoding="utf-8")
            os.environ.pop("LINEAR_API_KEY", None)
            os.environ["LINEAR_PROJECT_SLUG"] = "project"
            config = resolve_config(load_workflow(path))
            with self.assertRaises(ConfigValidationError):
                validate_dispatch_config(config)

    def test_cwd_default_workflow_path(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "WORKFLOW.md"
            path.write_text("hello", encoding="utf-8")
            workflow = load_workflow(cwd=Path(directory))
            self.assertEqual(workflow.prompt_template, "hello")
            self.assertEqual(workflow.config, {})

    def test_reloader_keeps_last_known_good_after_invalid_edit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "WORKFLOW.md"
            path.write_text(WORKFLOW, encoding="utf-8")
            os.environ["LINEAR_API_KEY"] = "token"
            os.environ["LINEAR_PROJECT_SLUG"] = "project"
            reloader = WorkflowReloader(path)
            workflow, config = reloader.load_initial()
            self.assertIn("Issue", workflow.prompt_template)
            path.write_text("---\ntracker\n---\nbroken", encoding="utf-8")
            os.utime(path, ns=(path.stat().st_atime_ns, path.stat().st_mtime_ns + 1_000_000_000))
            self.assertIsNone(reloader.reload_if_changed())
            self.assertIsNotNone(reloader.last_error)
            self.assertEqual(reloader.last_good[1].tracker_api_key, config.tracker_api_key)

    def test_reloader_detects_content_change_when_mtime_and_size_match(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "WORKFLOW.md"
            os.environ["LINEAR_API_KEY"] = "token"
            os.environ["LINEAR_PROJECT_SLUG"] = "project"
            path.write_text(workflow_text(prompt="Issue {{ issue.identifier }}"), encoding="utf-8")
            reloader = WorkflowReloader(path)
            reloader.load_initial()
            original_stat = path.stat()
            path.write_text(workflow_text(prompt="Task! {{ issue.identifier }}"), encoding="utf-8")
            self.assertEqual(path.stat().st_size, original_stat.st_size)
            os.utime(path, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
            reloaded = reloader.reload_if_changed()
            self.assertIsNotNone(reloaded)
            self.assertIn("Task!", reloaded[0].prompt_template)

    def test_prompt_rendering_is_strict(self):
        issue = Issue(id="id", identifier="ABC-1", title="Title", state="Todo")
        self.assertEqual(render_prompt("{{ issue.identifier }}", issue), "ABC-1")
        with self.assertRaises(TemplateRenderError):
            render_prompt("{{ issue.missing }}", issue)
        for template in ("{{ issue.identifier | upcase }}", "{{ issue.identifier ", "{{ }}", "{{ issue[0] }}", "}} {{ issue.identifier"):
            with self.subTest(template=template):
                with self.assertRaises(TemplateRenderError):
                    render_prompt(template, issue)

    def test_documented_yaml_subset_rejects_unsupported_shapes(self):
        with self.assertRaises(WorkflowParseError):
            parse_simple_yaml("- top-level-list")
