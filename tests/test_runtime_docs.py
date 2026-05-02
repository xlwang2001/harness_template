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
            "harness/runtime/state_persistence.py",
            "tests/runtime/test_workflow.py",
            "tests/runtime/test_orchestrator.py",
            "tests/runtime/test_tracker.py",
            "tests/runtime/test_codex_schema.py",
            "tests/runtime/test_state_persistence.py",
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

    def test_production_readiness_checklist_exists_and_is_linked(self):
        root = Path(__file__).resolve().parent.parent
        checklist = root / "docs" / "runtime" / "production-readiness-checklist.md"
        self.assertTrue(checklist.is_file())
        text = checklist.read_text(encoding="utf-8")
        for expected in (
            "make integration-test",
            "make codex-schema-test",
            "HARNESS_RUN_INTEGRATION=1",
            "Codex app-server",
            "read-only",
        ):
            self.assertIn(expected, text)
        for doc in (
            root / "docs" / "README.md",
            root / "docs" / "maintaining-this-scaffold.md",
            root / "docs" / "runtime" / "README.md",
            root / "docs" / "runtime" / "runbooks.md",
        ):
            self.assertIn("docs/runtime/production-readiness-checklist.md", doc.read_text(encoding="utf-8"))

    def test_template_upgrade_and_release_policies_exist_and_are_linked(self):
        root = Path(__file__).resolve().parent.parent
        upgrade = root / "docs" / "template-upgrade-policy.md"
        release = root / "docs" / "release-compatibility-policy.md"
        self.assertTrue(upgrade.is_file())
        self.assertTrue(release.is_file())
        self.assertIn("does not provide a `harness upgrade` command", upgrade.read_text(encoding="utf-8"))
        self.assertIn("Release Notes Requirements", release.read_text(encoding="utf-8"))
        docs_index = (root / "docs" / "README.md").read_text(encoding="utf-8")
        maintainer_doc = (root / "docs" / "maintaining-this-scaffold.md").read_text(encoding="utf-8")
        for path in ("docs/template-upgrade-policy.md", "docs/release-compatibility-policy.md"):
            self.assertIn(path, docs_index)
            self.assertIn(path, maintainer_doc)

    def test_implementation_plan_matches_copy_only_upgrade_policy(self):
        root = Path(__file__).resolve().parent.parent
        plan = (root / "symphony-harness-engineering-scaffold-plan.md").read_text(encoding="utf-8")
        self.assertIn("does not provide automatic in-place template upgrades", plan)
        self.assertNotIn("through `harness upgrade`, not silently", plan)
        self.assertIn("### Phase 0 — SPEC reference and design decisions", plan)
        self.assertIn("SPEC compatibility process", plan)
        self.assertNotIn("Upstream pinning", plan)
        self.assertNotIn("Symphony is an reference implementation", plan)

    def test_conformance_todo_tracks_prioritized_remaining_hardening(self):
        root = Path(__file__).resolve().parent.parent
        todo = root / "docs" / "runtime" / "spec-conformance-todo.md"
        text = todo.read_text(encoding="utf-8")
        self.assertIn("## Prioritized Remaining Hardening", text)
        self.assertIn("- [x] P0: Expand the gated real integration profile", text)
        self.assertIn("- [x] P1: Add a production-readiness checklist", text)
        self.assertIn("- [x] P2: Add configurable runtime log sinks", text)
        self.assertIn("- [x] P3: Revisit `linear_graphql` startup advertisement", text)
        prioritized = text.split("## Prioritized Remaining Hardening", 1)[1].split("## Future Recommended Extensions", 1)[0]
        self.assertNotIn("- [ ] P", prioritized)

    def test_conformance_todo_tracks_future_recommended_extensions(self):
        root = Path(__file__).resolve().parent.parent
        todo = root / "docs" / "runtime" / "spec-conformance-todo.md"
        text = todo.read_text(encoding="utf-8")
        self.assertIn("## Future Recommended Extensions", text)
        for item in (
            "- [x] Persist retry queue and session metadata",
            "- [x] Add first-class tracker write APIs",
            "pluggable issue tracker adapters beyond Linear",
            "schema-backed `linear_graphql` startup advertisement",
        ):
            self.assertIn(item, text)

    def test_tracker_write_apis_are_documented_as_explicit(self):
        root = Path(__file__).resolve().parent.parent
        runtime_readme = (root / "docs" / "runtime" / "README.md").read_text(encoding="utf-8")
        runbooks = (root / "docs" / "runtime" / "runbooks.md").read_text(encoding="utf-8")
        for expected in ("add_comment", "transition_issue", "record_pull_request"):
            self.assertIn(expected, runtime_readme)
            self.assertIn(expected, runbooks)
        self.assertIn("orchestrator does not call these by default", runtime_readme)
        self.assertIn("Keep real integration tests read-only", runbooks)

    def test_runtime_state_persistence_is_documented(self):
        root = Path(__file__).resolve().parent.parent
        runtime_readme = (root / "docs" / "runtime" / "README.md").read_text(encoding="utf-8")
        runbooks = (root / "docs" / "runtime" / "runbooks.md").read_text(encoding="utf-8")
        for text in (runtime_readme, runbooks):
            self.assertIn("runtime_state.file", text)
            self.assertIn("runtime_state.persist_retries", text)
            self.assertIn("runtime_state.persist_sessions", text)
        self.assertIn("runtime_state_load_failed", runbooks)
        self.assertIn("runtime_state_save_failed", runbooks)
