import unittest

from harness.project_profiles import get_profile
from harness.templates import TEMPLATE_ROOT, copy_templates, iter_template_files, render_template


class TemplateTests(unittest.TestCase):
    def test_template_discovery_finds_core_files(self):
        names = {path.name for path in iter_template_files()}
        relative_names = {path.relative_to(TEMPLATE_ROOT).as_posix() for path in iter_template_files()}
        self.assertIn("AGENTS.md", names)
        self.assertIn("WORKFLOW.md", names)
        self.assertIn("docs/README.md", relative_names)

    def test_profile_rendering(self):
        profile = get_profile("toy-example")
        text = render_template("{{ profile.name }} {{ profile.max_concurrent_agents }}", profile)
        self.assertEqual(text, "toy-example 1")

    def test_copy_templates_creates_expected_files(self):
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            from pathlib import Path

            tmp_path = Path(directory)
            operations = copy_templates(tmp_path, get_profile("toy-example"))
            self.assertTrue(operations)
            self.assertTrue((tmp_path / "AGENTS.md").is_file())
            self.assertTrue((tmp_path / "WORKFLOW.md").is_file())
            self.assertTrue((tmp_path / "docs" / "README.md").is_file())
            self.assertNotIn("{{ profile.name }}", (tmp_path / "WORKFLOW.md").read_text(encoding="utf-8"))
