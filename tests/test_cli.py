import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from harness.cli import main


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
