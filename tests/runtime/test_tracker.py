import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from harness.runtime.models import RuntimeConfig
from harness.runtime.tracker import LinearClient, TrackerError, normalize_linear_issue


def config():
    from pathlib import Path

    return RuntimeConfig(
        workflow_path=Path("WORKFLOW.md"),
        tracker_kind="linear",
        tracker_endpoint="https://api.linear.app/graphql",
        tracker_api_key="token",
        tracker_project_slug="project",
        active_states=("Todo",),
        terminal_states=("Done",),
        polling_interval_ms=30000,
        workspace_root=Path("/tmp/workspaces"),
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


class TrackerTests(unittest.TestCase):
    def test_normalizes_linear_issue(self):
        issue = normalize_linear_issue(
            {
                "id": "id1",
                "identifier": "ABC-1",
                "title": "Title",
                "priority": "2",
                "state": {"name": "Todo"},
                "labels": {"nodes": [{"name": "Backend"}]},
                "inverseRelations": {
                    "nodes": [
                        {"type": "blocks", "issue": {"id": "id0", "identifier": "ABC-0", "state": {"name": "Done"}}},
                        {"type": "relates", "issue": {"id": "id9", "identifier": "ABC-9"}},
                    ]
                },
            }
        )
        self.assertEqual(issue.priority, 2)
        self.assertEqual(issue.labels, ("backend",))
        self.assertEqual(issue.blocked_by[0].identifier, "ABC-0")

    def test_normalizes_multiple_blocker_shapes_and_ignores_unrelated_relations(self):
        issue = normalize_linear_issue(
            {
                "id": "id2",
                "identifier": "ABC-2",
                "title": "Title",
                "state": {"name": "Todo"},
                "labels": {"nodes": [{"name": "Backend"}, {"name": "URGENT"}]},
                "inverseRelations": {
                    "nodes": [
                        {"type": "blocks", "issue": {"id": "id0", "identifier": "ABC-0", "state": {"name": "Done"}}},
                        {"type": "blocks", "issue": {"id": "id1", "identifier": "ABC-1"}},
                        {"type": "related", "issue": {"id": "id9", "identifier": "ABC-9", "state": {"name": "Todo"}}},
                    ]
                },
            }
        )
        self.assertEqual(issue.labels, ("backend", "urgent"))
        self.assertEqual([blocker.identifier for blocker in issue.blocked_by], ["ABC-0", "ABC-1"])
        self.assertEqual(issue.blocked_by[0].state, "Done")
        self.assertIsNone(issue.blocked_by[1].state)

    def test_fetch_issues_by_empty_states_skips_api(self):
        client = LinearClient(config())
        with patch.object(client, "_graphql") as graphql:
            self.assertEqual(client.fetch_issues_by_states([]), [])
            graphql.assert_not_called()

    def test_pagination_preserves_order(self):
        class PagingClient(LinearClient):
            def __init__(self):
                super().__init__(config())
                self.calls = 0

            def _graphql(self, query, variables):
                self.calls += 1
                if self.calls == 1:
                    return {"data": {"issues": {"nodes": [{"id": "1", "identifier": "A", "title": "A", "state": {"name": "Todo"}}], "pageInfo": {"hasNextPage": True, "endCursor": "cursor"}}}}
                return {"data": {"issues": {"nodes": [{"id": "2", "identifier": "B", "title": "B", "state": {"name": "Todo"}}], "pageInfo": {"hasNextPage": False, "endCursor": None}}}}

        issues = PagingClient().fetch_candidate_issues()
        self.assertEqual([item.identifier for item in issues], ["A", "B"])

    def test_malformed_payload_maps_error(self):
        class BadClient(LinearClient):
            def _graphql(self, query, variables):
                return {"data": {"issues": None}}

        with self.assertRaisesRegex(TrackerError, "linear_unknown_payload"):
            BadClient(config()).fetch_candidate_issues()

    def test_graphql_errors_map_error(self):
        class ErrorClient(LinearClient):
            def _graphql(self, query, variables):
                raise TrackerError("linear_graphql_errors")

        with self.assertRaisesRegex(TrackerError, "linear_graphql_errors"):
            ErrorClient(config()).fetch_candidate_issues()

    def test_http_and_transport_errors_are_mapped(self):
        client = LinearClient(config())
        with patch("urllib.request.urlopen", side_effect=HTTPError("url", 500, "bad", {}, None)):
            with self.assertRaisesRegex(TrackerError, "linear_api_status"):
                client._graphql("query", {})
        with patch("urllib.request.urlopen", side_effect=URLError("down")):
            with self.assertRaisesRegex(TrackerError, "linear_api_request"):
                client._graphql("query", {})
