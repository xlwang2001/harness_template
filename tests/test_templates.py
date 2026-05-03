import unittest
import tempfile
from importlib import resources
from pathlib import Path

from harness.project_profiles import get_profile
from harness.templates import TEMPLATE_ROOT, copy_templates, iter_template_files, plan_copy, render_template


class TemplateTests(unittest.TestCase):
    def test_template_discovery_finds_core_files(self):
        names = {path.name for path in iter_template_files()}
        relative_names = {operation.relative_path.as_posix() for operation in plan_copy(Path("/tmp/harness-template-test"), TEMPLATE_ROOT)}
        self.assertIn("AGENTS.md", names)
        self.assertIn("WORKFLOW.md", names)
        self.assertIn("docs/README.md", relative_names)
        self.assertIn("docs/review-packet-template.md", relative_names)
        self.assertIn("docs/generated/review-packet.schema.json", relative_names)
        self.assertIn(".codex/hooks/pre_tool_use_policy.py", relative_names)
        self.assertIn(".github/workflows/harness-docs.yml", relative_names)

    def test_packaged_template_resources_are_available(self):
        root = resources.files("harness").joinpath("template_data", "repo")
        self.assertTrue(root.joinpath("WORKFLOW.md").is_file())
        self.assertTrue(root.joinpath(".codex", "hooks", "pre_tool_use_policy.py").is_file())
        self.assertTrue(root.joinpath(".github", "workflows", "harness-docs.yml").is_file())

    def test_profile_rendering(self):
        profile = get_profile("toy-example")
        text = render_template("{{ profile.name }} {{ profile.max_concurrent_agents }}", profile)
        self.assertEqual(text, "toy-example 1")

    def test_copy_templates_creates_expected_files(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            operations = copy_templates(tmp_path, get_profile("toy-example"))
            self.assertTrue(operations)
            self.assertTrue((tmp_path / "AGENTS.md").is_file())
            self.assertTrue((tmp_path / "WORKFLOW.md").is_file())
            self.assertTrue((tmp_path / "docs" / "README.md").is_file())
            self.assertNotIn("{{ profile.name }}", (tmp_path / "WORKFLOW.md").read_text(encoding="utf-8"))
