import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from harness.runtime.client_tools import ClientToolResult, LinearGraphQLTool, build_client_tools
from harness.runtime.models import RuntimeConfig
from harness.runtime.tracker import LinearClient, TrackerError, normalize_linear_issue


def config(**overrides):
    from pathlib import Path

    values = {
        "workflow_path": Path("WORKFLOW.md"),
        "tracker_kind": "linear",
        "tracker_endpoint": "https://api.linear.app/graphql",
        "tracker_api_key": "token",
        "tracker_project_slug": "project",
        "active_states": ("Todo",),
        "terminal_states": ("Done",),
        "polling_interval_ms": 30000,
        "workspace_root": Path("/tmp/workspaces"),
        "hooks": {"after_create": None, "before_run": None, "after_run": None, "before_remove": None},
        "hooks_timeout_ms": 1000,
        "max_concurrent_agents": 1,
        "max_turns": 20,
        "max_retry_backoff_ms": 300000,
        "max_concurrent_agents_by_state": {},
        "codex_command": "true",
        "codex_turn_timeout_ms": 1000,
        "codex_read_timeout_ms": 1000,
        "codex_stall_timeout_ms": 300000,
        "approval_policy": "on-request",
        "thread_sandbox": "workspace-write",
        "turn_sandbox_policy": "workspace-write",
    }
    values.update(overrides)
    return RuntimeConfig(**values)


class FakeResponse:
    def __init__(self, payload, *, status=200):
        self.payload = payload
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return self.payload


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

    def test_build_client_tools_registers_linear_graphql_for_linear_tracker(self):
        self.assertIn("linear_graphql", build_client_tools(config()))
        self.assertEqual(build_client_tools(config(tracker_kind="github")), {})

    def test_linear_graphql_accepts_raw_query_string(self):
        tool = LinearGraphQLTool(config())
        with patch("urllib.request.urlopen", return_value=FakeResponse(b'{"data":{"viewer":{"id":"me"}}}')) as urlopen:
            result = tool("query Viewer { viewer { id } }")
        self.assertEqual(result, ClientToolResult(success=True, output={"data": {"viewer": {"id": "me"}}}))
        request = urlopen.call_args.args[0]
        self.assertEqual(request.headers["Authorization"], "token")
        self.assertEqual(request.headers["Content-type"], "application/json")
        body = request.data.decode("utf-8")
        self.assertIn("query Viewer", body)
        self.assertIn('"variables": {}', body)

    def test_linear_graphql_accepts_query_and_variables_mapping(self):
        tool = LinearGraphQLTool(config())
        with patch("urllib.request.urlopen", return_value=FakeResponse(b'{"data":{"issue":{"id":"1"}}}')):
            result = tool({"query": "query Issue($id: String!) { issue(id: $id) { id } }", "variables": {"id": "abc"}})
        self.assertTrue(result.success)
        self.assertEqual(result.output["data"]["issue"]["id"], "1")

    def test_linear_graphql_preserves_graphql_errors_as_failure(self):
        tool = LinearGraphQLTool(config())
        payload = {"errors": [{"message": "bad query"}], "data": None}
        with patch("urllib.request.urlopen", return_value=FakeResponse(b'{"errors":[{"message":"bad query"}],"data":null}')):
            result = tool("query Bad { nope }")
        self.assertFalse(result.success)
        self.assertEqual(result.output, {"error": "linear_graphql_errors", "response": payload})

    def test_linear_graphql_rejects_invalid_inputs(self):
        tool = LinearGraphQLTool(config())
        cases = [
            ("", "empty_query"),
            ({"query": 12}, "invalid_query"),
            ({"query": "query A { a }", "variables": []}, "invalid_variables"),
            ({"query": "query A { a }", "operationName": "A"}, "operation_name_not_supported"),
            ("query A { a } mutation B { b }", "invalid_operation_count"),
        ]
        for arguments, error in cases:
            with self.subTest(error=error):
                result = tool(arguments)
                self.assertFalse(result.success)
                self.assertEqual(result.output["error"], error)

    def test_linear_graphql_reports_missing_auth_and_unsupported_tracker(self):
        self.assertEqual(LinearGraphQLTool(config(tracker_api_key=None))("query A { a }").output["error"], "missing_auth")
        self.assertEqual(LinearGraphQLTool(config(tracker_kind="github"))("query A { a }").output["error"], "unsupported_tracker_kind")

    def test_linear_graphql_maps_http_transport_and_malformed_payloads(self):
        tool = LinearGraphQLTool(config())
        with patch("urllib.request.urlopen", side_effect=HTTPError("url", 429, "rate limited", {}, None)):
            self.assertEqual(tool("query A { a }").output, {"error": "linear_api_status", "status": 429})
        with patch("urllib.request.urlopen", side_effect=URLError("down")):
            self.assertEqual(tool("query A { a }").output, {"error": "linear_api_request", "reason": "down"})
        with patch("urllib.request.urlopen", return_value=FakeResponse(b"not-json")):
            self.assertEqual(tool("query A { a }").output, {"error": "linear_unknown_payload"})
