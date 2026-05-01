import json
import os
import shlex
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from harness.runtime.agent import AgentRunnerError, CodexAgentRunner
from harness.runtime.models import Issue, RuntimeConfig
from harness.runtime.workspace import WorkspaceError


def config(root: Path, *, command: str, read_timeout_ms: int = 1000, turn_timeout_ms: int = 1000) -> RuntimeConfig:
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
        codex_command=command,
        codex_turn_timeout_ms=turn_timeout_ms,
        codex_read_timeout_ms=read_timeout_ms,
        codex_stall_timeout_ms=300000,
        approval_policy="on-request",
        thread_sandbox="workspace-write",
        turn_sandbox_policy="workspace-write",
    )


def issue() -> Issue:
    return Issue(id="abc-1", identifier="ABC-1", title="Test issue", state="Todo", url="https://example.test/ABC-1")


FAKE_SERVER = r"""
import json
import os
import sys
import time

mode = os.environ.get("FAKE_CODEX_MODE", "success")
record_path = os.environ.get("FAKE_CODEX_RECORD")
records = []


def send(message):
    print(json.dumps(message), flush=True)


def record(message):
    records.append(message)
    if record_path:
        with open(record_path, "w", encoding="utf-8") as handle:
            json.dump(records, handle)


if mode == "exit_before_response":
    sys.exit(7)

for line in sys.stdin:
    message = json.loads(line)
    record(message)
    method = message.get("method")
    request_id = message.get("id")
    if method == "initialize":
        if mode == "read_timeout":
            time.sleep(2)
            continue
        send({"jsonrpc": "2.0", "id": request_id, "result": {"ok": True}})
    elif method == "thread/create":
        send({"jsonrpc": "2.0", "id": request_id, "result": {"thread": {"id": "thread-1"}}})
    elif method == "turn/start":
        send({"jsonrpc": "2.0", "id": request_id, "result": {"turn_id": "turn-1"}})
        if mode == "success":
            send({"event": "notification", "message": "working"})
            send({
                "event": "thread/tokenUsage/updated",
                "usage": {"input_tokens": 5, "output_tokens": 6, "total_tokens": 11},
                "rate_limits": {"primary": {"remaining": 10}},
            })
            send({"event": "turn_completed"})
        elif mode == "failure":
            send({"event": "turn_failed", "message": "bad turn"})
        elif mode == "cancelled":
            send({"event": "turn_cancelled"})
        elif mode == "input_required":
            send({"event": "turn_input_required"})
        elif mode == "turn_timeout":
            time.sleep(2)
        elif mode == "exit_during_turn":
            sys.exit(9)
    elif method == "shutdown":
        sys.exit(0)
"""


class CodexAgentRunnerTests(unittest.TestCase):
    def build_runner(self, root: Path, mode: str, *, read_timeout_ms: int = 1000, turn_timeout_ms: int = 1000):
        server = root / "fake_codex_server.py"
        record = root / "record.json"
        server.write_text(textwrap.dedent(FAKE_SERVER), encoding="utf-8")
        workspace = root / "workspace"
        workspace.mkdir()
        command = " ".join(
            [
                f"FAKE_CODEX_MODE={shlex.quote(mode)}",
                f"FAKE_CODEX_RECORD={shlex.quote(str(record))}",
                shlex.quote(sys.executable),
                shlex.quote(str(server)),
            ]
        )
        cfg = config(root, command=command, read_timeout_ms=read_timeout_ms, turn_timeout_ms=turn_timeout_ms)
        return CodexAgentRunner(cfg), workspace, record

    def test_protocol_success_launches_in_workspace_and_streams_events(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner, workspace, record = self.build_runner(root, "success")
            events = []

            result = runner.run_turn(issue(), "Do the work", workspace, on_event=events.append)

            self.assertTrue(result.success)
            self.assertEqual(result.session_id, "thread-1-turn-1")
            self.assertEqual([event["event"] for event in events], ["session_started", "notification", "thread/tokenUsage/updated", "turn_completed"])
            self.assertEqual(events[0]["thread_id"], "thread-1")
            self.assertEqual(events[0]["turn_id"], "turn-1")
            self.assertEqual(events[2]["rate_limits"], {"primary": {"remaining": 10}})
            records = json.loads(record.read_text(encoding="utf-8"))
            self.assertEqual([message["method"] for message in records[:3]], ["initialize", "thread/create", "turn/start"])
            self.assertEqual(records[0]["params"]["cwd"], str(workspace.resolve()))
            self.assertEqual(records[0]["params"]["approval_policy"], "on-request")
            self.assertEqual(records[0]["params"]["thread_sandbox"], "workspace-write")
            self.assertEqual(records[2]["params"]["prompt"], "Do the work")
            self.assertEqual(records[2]["params"]["thread_id"], "thread-1")
            self.assertEqual(records[2]["params"]["metadata"]["issue_identifier"], "ABC-1")

    def test_protocol_turn_failure_maps_to_runner_error(self):
        with tempfile.TemporaryDirectory() as directory:
            runner, workspace, _ = self.build_runner(Path(directory), "failure")
            with self.assertRaisesRegex(AgentRunnerError, "turn_failed"):
                runner.run_turn(issue(), "Do the work", workspace)

    def test_protocol_turn_cancellation_maps_to_runner_error(self):
        with tempfile.TemporaryDirectory() as directory:
            runner, workspace, _ = self.build_runner(Path(directory), "cancelled")
            with self.assertRaisesRegex(AgentRunnerError, "turn_cancelled"):
                runner.run_turn(issue(), "Do the work", workspace)

    def test_protocol_user_input_required_fails_without_stalling(self):
        with tempfile.TemporaryDirectory() as directory:
            runner, workspace, _ = self.build_runner(Path(directory), "input_required")
            with self.assertRaisesRegex(AgentRunnerError, "turn_input_required"):
                runner.run_turn(issue(), "Do the work", workspace)

    def test_protocol_read_timeout_maps_to_response_timeout(self):
        with tempfile.TemporaryDirectory() as directory:
            runner, workspace, _ = self.build_runner(Path(directory), "read_timeout", read_timeout_ms=50)
            with self.assertRaisesRegex(AgentRunnerError, "response_timeout"):
                runner.run_turn(issue(), "Do the work", workspace)

    def test_protocol_turn_timeout_maps_to_turn_timeout(self):
        with tempfile.TemporaryDirectory() as directory:
            runner, workspace, _ = self.build_runner(Path(directory), "turn_timeout", turn_timeout_ms=50)
            with self.assertRaisesRegex(AgentRunnerError, "turn_timeout"):
                runner.run_turn(issue(), "Do the work", workspace)

    def test_protocol_subprocess_exit_maps_to_port_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            runner, workspace, _ = self.build_runner(Path(directory), "exit_during_turn")
            with self.assertRaisesRegex(AgentRunnerError, "port_exit"):
                runner.run_turn(issue(), "Do the work", workspace)

    def test_protocol_rejects_workspace_outside_root(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            runner, _, _ = self.build_runner(Path(directory), "success")
            with self.assertRaises(WorkspaceError):
                runner.run_turn(issue(), "Do the work", Path(outside))


if __name__ == "__main__":
    unittest.main()
