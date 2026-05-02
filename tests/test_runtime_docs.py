import unittest
from pathlib import Path


class RuntimeDocsTests(unittest.TestCase):
    def test_spec_conformance_matrix_exists_and_has_core_structure(self):
        root = Path(__file__).resolve().parent.parent
        matrix = root / "docs" / "runtime" / "spec-conformance-matrix.md"
        self.assertTrue(matrix.is_file())
        text = matrix.read_text(encoding="utf-8")
        for status in ("Implemented", "Partial", "Planned", "Deferred"):
            self.assertIn(status, text)
        for reference in (
            "harness/runtime/workflow.py",
            "harness/runtime/orchestrator.py",
            "harness/runtime/workspace.py",
            "harness/runtime/agent.py",
            "harness/runtime/tracker.py",
            "tests/runtime/test_workflow.py",
            "tests/runtime/test_orchestrator.py",
            "tests/runtime/test_tracker.py",
        ):
            self.assertIn(reference, text)

    def test_conformance_todo_marks_matrix_complete(self):
        root = Path(__file__).resolve().parent.parent
        todo = root / "docs" / "runtime" / "spec-conformance-todo.md"
        text = todo.read_text(encoding="utf-8")
        self.assertIn("- [x] Add a runtime conformance matrix mapped to upstream SPEC sections.", text)

    def test_runtime_runbooks_cover_operator_topics(self):
        root = Path(__file__).resolve().parent.parent
        runbooks = root / "docs" / "runtime" / "runbooks.md"
        self.assertTrue(runbooks.is_file())
        text = runbooks.read_text(encoding="utf-8")
        for heading in (
            "## Workspace Cleanup",
            "## Logs And Observability",
            "## Failure Modes",
            "## Dashboard And API Operation",
            "## SPEC Compatibility Upgrades",
        ):
            self.assertIn(heading, text)
        self.assertIn("docs/runtime/runbooks.md", (root / "docs" / "README.md").read_text(encoding="utf-8"))
        self.assertIn("docs/runtime/runbooks.md", (root / "docs" / "runtime" / "README.md").read_text(encoding="utf-8"))
