import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from harness.runtime.models import Issue, RetryEntry, RunAttemptRecord, RuntimeConfig, RunningEntry, RuntimeState
from harness.runtime.orchestrator import Orchestrator
from harness.runtime.status_server import handle_status_request


def config(root: Path) -> RuntimeConfig:
    return RuntimeConfig(
        workflow_path=root / "WORKFLOW.md",
        tracker_kind="linear",
        tracker_endpoint="https://api.linear.app/graphql",
        tracker_api_key="token",
        tracker_project_slug="project",
        active_states=("Todo", "In Progress"),
        terminal_states=("Done", "Cancelled"),
        polling_interval_ms=30000,
        workspace_root=root,
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


def issue(identifier, *, state="In Progress") -> Issue:
    return Issue(id=identifier.lower(), identifier=identifier, title=f"{identifier} title", state=state)


class FakeOrchestrator:
    def __init__(self, root: Path):
        self.config = config(root)
        self.state = RuntimeState(poll_interval_ms=30000, max_concurrent_agents=1)
        running = issue("ABC-1")
        self.state.running[running.id] = RunningEntry(
            issue=running,
            started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            workspace_path=root / "ABC-1",
            session_id="thread-1-turn-1",
            turn_count=2,
            last_codex_event="notification",
            codex_input_tokens=3,
            codex_output_tokens=4,
            codex_total_tokens=7,
        )
        self.state.retry_attempts["abc-2"] = RetryEntry(issue_id="abc-2", identifier="ABC-2", attempt=3, due_at_ms=12345, error="later")
        self.state.last_attempts["abc-3"] = RunAttemptRecord(
            issue_id="abc-3",
            identifier="ABC-3",
            attempt=1,
            workspace_path=root / "ABC-3",
            started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            finished_at=datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
            status="failed",
            error="boom",
        )

    def snapshot(self):
        return {
            "generated_at": "2026-01-01T00:00:00+00:00",
            "counts": {"running": len(self.state.running), "retrying": len(self.state.retry_attempts)},
            "running": [{"issue_identifier": "ABC-1"}],
            "retrying": [retry.__dict__ for retry in self.state.retry_attempts.values()],
            "codex_totals": {"input_tokens": 3, "output_tokens": 4, "total_tokens": 7, "seconds_running": 12.5},
            "rate_limits": {"primary": {"remaining": 5}},
        }

    def issue_detail(self, identifier):
        return Orchestrator.issue_detail(self, identifier)

    def _running_detail(self, entry):
        return Orchestrator._running_detail(self, entry)

    def _attempt_detail(self, attempt):
        return Orchestrator._attempt_detail(self, attempt)


class RefreshRecorder:
    def __init__(self):
        self.pending = False

    def __call__(self):
        coalesced = self.pending
        self.pending = True
        return coalesced


class RuntimeHTTPTests(unittest.TestCase):
    def build_router(self, root: Path):
        refresh = RefreshRecorder()
        orchestrator = FakeOrchestrator(root)
        return orchestrator, refresh

    def request_json(self, method, path, orchestrator, refresh):
        status, content_type, body = handle_status_request(method, path, orchestrator, refresh)
        self.assertEqual(content_type, "application/json")
        return status, json.loads(body.decode("utf-8"))

    def test_get_state_returns_snapshot_json(self):
        with tempfile.TemporaryDirectory() as directory:
            orchestrator, refresh = self.build_router(Path(directory))
            status, payload = self.request_json("GET", "/api/v1/state", orchestrator, refresh)
            self.assertEqual(status, 200)
            self.assertEqual(payload["counts"], {"running": 1, "retrying": 1})

    def test_get_issue_details_for_running_retry_and_last_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            orchestrator, refresh = self.build_router(Path(directory))
            _, running = self.request_json("GET", "/api/v1/ABC-1", orchestrator, refresh)
            _, retry = self.request_json("GET", "/api/v1/ABC-2", orchestrator, refresh)
            _, attempt = self.request_json("GET", "/api/v1/ABC-3", orchestrator, refresh)
            self.assertEqual(running["status"], "running")
            self.assertEqual(running["running"]["tokens"]["total_tokens"], 7)
            self.assertEqual(retry["status"], "retrying")
            self.assertEqual(retry["retry"]["attempt"], 3)
            self.assertEqual(attempt["status"], "failed")
            self.assertEqual(attempt["last_attempt"]["error"], "boom")

    def test_unknown_issue_and_path_return_error_envelopes(self):
        with tempfile.TemporaryDirectory() as directory:
            orchestrator, refresh = self.build_router(Path(directory))
            status, payload = self.request_json("GET", "/api/v1/NOPE", orchestrator, refresh)
            self.assertEqual(status, 404)
            self.assertEqual(payload["error"]["code"], "issue_not_found")
            status, payload = self.request_json("GET", "/missing", orchestrator, refresh)
            self.assertEqual(status, 404)
            self.assertEqual(payload["error"]["code"], "not_found")

    def test_unsupported_methods_return_405_json_error(self):
        with tempfile.TemporaryDirectory() as directory:
            orchestrator, refresh = self.build_router(Path(directory))
            status, payload = self.request_json("POST", "/api/v1/state", orchestrator, refresh)
            self.assertEqual(status, 405)
            self.assertEqual(payload["error"]["code"], "method_not_allowed")
            status, payload = self.request_json("GET", "/api/v1/refresh", orchestrator, refresh)
            self.assertEqual(status, 405)
            self.assertEqual(payload["error"]["code"], "method_not_allowed")

    def test_refresh_queues_and_coalesces(self):
        with tempfile.TemporaryDirectory() as directory:
            orchestrator, refresh = self.build_router(Path(directory))
            status, first = self.request_json("POST", "/api/v1/refresh", orchestrator, refresh)
            status, second = self.request_json("POST", "/api/v1/refresh", orchestrator, refresh)
            self.assertEqual(status, 202)
            self.assertTrue(first["queued"])
            self.assertFalse(first["coalesced"])
            self.assertTrue(second["coalesced"])
            self.assertTrue(refresh.pending)

    def test_dashboard_returns_html(self):
        with tempfile.TemporaryDirectory() as directory:
            orchestrator, refresh = self.build_router(Path(directory))
            status, content_type, raw = handle_status_request("GET", "/", orchestrator, refresh)
            body = raw.decode("utf-8")
            self.assertEqual(status, 200)
            self.assertIn("text/html", content_type)
            self.assertIn("/api/v1/state", body)
            self.assertIn("Running: 1", body)
            self.assertIn("Retrying: 1", body)
            self.assertIn("Total tokens: 7", body)
            self.assertIn("Rate limits: present", body)

    def test_observability_failures_return_json_error(self):
        class BrokenOrchestrator(FakeOrchestrator):
            def snapshot(self):
                raise RuntimeError("snapshot failed")

        with tempfile.TemporaryDirectory() as directory:
            refresh = RefreshRecorder()
            status, payload = self.request_json("GET", "/api/v1/state", BrokenOrchestrator(Path(directory)), refresh)
            self.assertEqual(status, 503)
            self.assertEqual(payload["error"]["code"], "status_unavailable")


if __name__ == "__main__":
    unittest.main()
