import tomllib
import unittest
from pathlib import Path

import harness


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

    def test_changelog_documents_1_0_release_status_and_is_linked(self):
        root = Path(__file__).resolve().parent.parent
        changelog = root / "CHANGELOG.md"
        self.assertTrue(changelog.is_file())
        text = changelog.read_text(encoding="utf-8")
        for expected in (
            "## 1.4.0",
            "Installable package release",
            "## 1.3.1",
            "Workflow YAML subset visibility release",
            "## 1.3.0",
            "Adopted example release",
            "## 1.2.0",
            "Machine-checkable review packet release",
            "## 1.1.0",
            "Dispatch preview release",
            "## 1.0.1",
            "Runtime support matrix release",
            "## 1.0.0",
            "Linear-first hardened runtime release",
            "`linear_graphql` startup advertisement is schema-blocked",
            "Non-Linear tracker adapters are deferred",
            "Real Linear mutation integration remains separately gated",
            "Advanced workspace population, remote checkout, and remote execution remain future hardening",
        ):
            self.assertIn(expected, text)
        for doc in (
            root / "README.md",
            root / "docs" / "README.md",
            root / "docs" / "maintaining-this-scaffold.md",
        ):
            self.assertIn("CHANGELOG.md", doc.read_text(encoding="utf-8"))

    def test_package_version_is_current_release(self):
        root = Path(__file__).resolve().parent.parent
        pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(pyproject["project"]["version"], "1.4.0")
        self.assertEqual(harness.__version__, "1.4.0")

    def test_installable_package_docs_and_check_exist(self):
        root = Path(__file__).resolve().parent.parent
        readme = (root / "README.md").read_text(encoding="utf-8")
        adoption = (root / "docs" / "adoption-guide.md").read_text(encoding="utf-8")
        makefile = (root / "Makefile").read_text(encoding="utf-8")
        pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
        for text in (readme, adoption):
            self.assertIn("pipx install harness-engineering-starter --index-url <PRIVATE_INDEX_URL>", text)
            self.assertIn("do not need to clone", text)
            self.assertIn("harness init", text)
        self.assertIn("package-check:", makefile)
        self.assertIn("python3 -m harness.package_check", makefile)
        self.assertIn('include = ["harness*"]', pyproject)
        self.assertIn("template_data/**/*", pyproject)

    def test_runtime_support_matrix_exists_and_is_linked(self):
        root = Path(__file__).resolve().parent.parent
        matrix = root / "docs" / "runtime" / "support-matrix.md"
        self.assertTrue(matrix.is_file())
        text = matrix.read_text(encoding="utf-8")
        for expected in (
            "Linear tracker | Supported",
            "GitHub Issues tracker | Not supported",
            "`linear_graphql` startup advertisement | Schema-blocked",
            "Auto-merge | Not supported by default",
            "Durable local runtime state | Supported",
        ):
            self.assertIn(expected, text)
        for doc in (
            root / "README.md",
            root / "docs" / "README.md",
            root / "docs" / "adoption-guide.md",
            root / "docs" / "runtime" / "README.md",
            root / "docs" / "runtime" / "production-readiness-checklist.md",
        ):
            self.assertIn("docs/runtime/support-matrix.md", doc.read_text(encoding="utf-8"))

    def test_optimization_backlog_tracks_support_matrix_completion(self):
        root = Path(__file__).resolve().parent.parent
        todo = (root / "docs" / "runtime" / "spec-conformance-todo.md").read_text(encoding="utf-8")
        self.assertIn("## Optimization Backlog", todo)
        self.assertIn("- [x] Priority 1: Add a human-facing runtime support matrix", todo)
        self.assertIn("- [x] Priority 2: Add a read-only dispatch preview command", todo)
        self.assertIn("- [x] Priority 3: Make review packets machine-checkable", todo)
        self.assertIn("- [x] Priority 4: Add a complete adopted tiny CLI target-repo example", todo)
        self.assertIn("- [x] Priority 5: Make the `WORKFLOW.md` YAML subset visible", todo)

    def test_workflow_yaml_subset_is_documented_in_templates_and_docs(self):
        root = Path(__file__).resolve().parent.parent
        for path in (
            root / "templates" / "repo" / "WORKFLOW.md",
            root / "templates" / "symphony" / "WORKFLOW.md",
            root / "examples" / "adopted-tiny-cli" / "WORKFLOW.md",
        ):
            text = path.read_text(encoding="utf-8")
            self.assertIn("harness YAML subset", text)
            self.assertIn("Avoid anchors, aliases, merge keys, custom tags", text)
        for path in (
            root / "docs" / "adoption-guide.md",
            root / "docs" / "runtime" / "README.md",
        ):
            text = path.read_text(encoding="utf-8")
            self.assertIn("YAML subset", text)
            self.assertIn("anchors, aliases, merge keys, custom tags", text)

    def test_review_packet_templates_and_docs_exist(self):
        root = Path(__file__).resolve().parent.parent
        template = root / "templates" / "repo" / "docs" / "review-packet-template.md"
        schema = root / "templates" / "repo" / "docs" / "generated" / "review-packet.schema.json"
        skill = root / "templates" / "repo" / ".agents" / "skills" / "review-packet" / "SKILL.md"
        pr_template = root / "templates" / "repo" / ".github" / "pull_request_template.md"
        self.assertTrue(template.is_file())
        self.assertTrue(schema.is_file())
        self.assertIn("validate-review-packet", skill.read_text(encoding="utf-8"))
        self.assertIn("Review packet path", pr_template.read_text(encoding="utf-8"))

    def test_readme_describes_1_0_status_not_early_stage(self):
        root = Path(__file__).resolve().parent.parent
        readme = (root / "README.md").read_text(encoding="utf-8")
        plan = (root / "symphony-harness-engineering-scaffold-plan.md").read_text(encoding="utf-8")
        self.assertIn("1.0 Linear-first hardened runtime scaffold", readme)
        self.assertIn("1.0 Linear-first hardened runtime scaffold", plan)
        self.assertNotIn("early conformance stage", readme)
        self.assertNotIn("Early hardened runtime scaffold", readme)
        self.assertNotIn("Early hardened runtime scaffold", plan)

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
            "- [x] Defer pluggable issue tracker adapters beyond Linear",
            "schema-backed `linear_graphql` startup advertisement",
        ):
            self.assertIn(item, text)
        self.assertNotIn("- [ ] Add pluggable issue tracker adapters beyond Linear", text)

    def test_non_linear_trackers_are_deferred_for_linear_only_deployments(self):
        root = Path(__file__).resolve().parent.parent
        matrix = (root / "docs" / "runtime" / "spec-conformance-matrix.md").read_text(encoding="utf-8")
        runtime_readme = (root / "docs" / "runtime" / "README.md").read_text(encoding="utf-8")
        self.assertIn("Non-Linear adapters are deferred for Linear-only deployments", matrix)
        self.assertIn("Linear is the supported production tracker", runtime_readme)
        self.assertIn("GitHub Issues, Jira, or Shortcut are deferred", runtime_readme)

    def test_linear_graphql_startup_advertisement_remains_schema_blocked(self):
        root = Path(__file__).resolve().parent.parent
        matrix = (root / "docs" / "runtime" / "spec-conformance-matrix.md").read_text(encoding="utf-8")
        runtime_readme = (root / "docs" / "runtime" / "README.md").read_text(encoding="utf-8")
        self.assertIn("schema-backed `linear_graphql` startup advertisement", matrix)
        self.assertIn("no stable client-tool advertisement field", matrix)
        self.assertIn("does not send non-schema `client_tools`, `tools`, or `dynamicTools` fields", runtime_readme)

    def test_linear_mutation_profile_is_separately_gated_and_default_read_only(self):
        root = Path(__file__).resolve().parent.parent
        runbooks = (root / "docs" / "runtime" / "runbooks.md").read_text(encoding="utf-8")
        checklist = (root / "docs" / "runtime" / "production-readiness-checklist.md").read_text(encoding="utf-8")
        integration_tests = (root / "tests" / "runtime" / "test_integration_profile.py").read_text(encoding="utf-8")
        self.assertIn("HARNESS_RUN_LINEAR_MUTATION_INTEGRATION=1", runbooks)
        self.assertIn("HARNESS_RUN_LINEAR_MUTATION_INTEGRATION=1", checklist)
        self.assertIn("HARNESS_RUN_LINEAR_MUTATION_INTEGRATION", integration_tests)
        self.assertIn("The default integration profile must stay read-only", checklist)

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
