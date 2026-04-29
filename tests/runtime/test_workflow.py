import os
import tempfile
import unittest
from pathlib import Path

from harness.runtime.workflow import ConfigValidationError, load_workflow, resolve_config, validate_dispatch_config


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
            validate_dispatch_config(config)

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
