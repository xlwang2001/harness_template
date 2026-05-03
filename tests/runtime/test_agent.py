import json
import os
import shlex
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from harness.runtime.agent import AgentRunnerError, CodexAgentRunner
from harness.runtime.client_tools import ClientToolResult
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
turn_count = 0


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
    elif method == "thread/start":
        send({"jsonrpc": "2.0", "id": request_id, "result": {"thread": {"id": "thread-1"}}})
    elif method == "thread/name/set":
        send({"jsonrpc": "2.0", "id": request_id, "result": {}})
    elif method == "turn/start":
        turn_count += 1
        turn_id = f"turn-{turn_count}"
        send({"jsonrpc": "2.0", "id": request_id, "result": {"turn": {"id": turn_id, "items": [], "status": "running"}}})
        if mode == "success":
            send({"event": "notification", "message": "working"})
            send({
                "method": "thread/tokenUsage/updated",
                "params": {
                    "threadId": "thread-1",
                    "turnId": turn_id,
                    "tokenUsage": {
                        "last": {"inputTokens": 5, "outputTokens": 6, "totalTokens": 11, "cachedInputTokens": 0, "reasoningOutputTokens": 0},
                        "total": {"inputTokens": 5, "outputTokens": 6, "totalTokens": 11, "cachedInputTokens": 0, "reasoningOutputTokens": 0},
                    },
                },
            })
            send({"method": "account/rateLimits/updated", "params": {"rateLimits": {"primary": {"remaining": 10}}}})
            send({"method": "turn/completed", "params": {"threadId": "thread-1", "turn": {"id": turn_id, "items": [], "status": "completed"}}})
        elif mode == "multi_turn":
            send({"event": "notification", "message": f"working {turn_count}"})
            send({"method": "turn/completed", "params": {"threadId": "thread-1", "turn": {"id": turn_id, "items": [], "status": "completed"}}})
        elif mode == "failure":
            send({"method": "error", "params": {"threadId": "thread-1", "turnId": turn_id, "willRetry": False, "error": {"message": "bad turn"}}})
        elif mode == "cancelled":
            send({"event": "turn_cancelled"})
        elif mode == "input_required":
            send({"jsonrpc": "2.0", "id": "input-1", "method": "item/tool/requestUserInput", "params": {"threadId": "thread-1", "turnId": turn_id, "questions": []}})
            response = json.loads(sys.stdin.readline())
            record(response)
        elif mode == "approval_tools":
            send({"jsonrpc": "2.0", "id": "approval-1", "method": "item/commandExecution/requestApproval", "params": {"itemId": "item-approval-1", "threadId": "thread-1", "turnId": turn_id, "command": "pytest"}})
            approval = json.loads(sys.stdin.readline())
            record(approval)
            send({"jsonrpc": "2.0", "id": "permissions-1", "method": "item/permissions/requestApproval", "params": {"threadId": "thread-1", "turnId": turn_id, "permissions": {}}})
            permissions = json.loads(sys.stdin.readline())
            record(permissions)
            send({"jsonrpc": "2.0", "id": "tool-unsupported", "method": "item/tool/call", "params": {"callId": "tool-unsupported", "threadId": "thread-1", "turnId": turn_id, "tool": "missing_tool", "arguments": {"value": 1}}})
            unsupported = json.loads(sys.stdin.readline())
            record(unsupported)
            send({"jsonrpc": "2.0", "id": "tool-supported", "method": "item/tool/call", "params": {"callId": "tool-supported", "threadId": "thread-1", "turnId": turn_id, "tool": "echo", "arguments": {"value": 2}}})
            supported = json.loads(sys.stdin.readline())
            record(supported)
            send({"method": "turn/completed", "params": {"threadId": "thread-1", "turn": {"id": turn_id, "items": [], "status": "completed"}}})
        elif mode == "linear_graphql":
            send({"jsonrpc": "2.0", "id": "linear-1", "method": "item/tool/call", "params": {"callId": "linear-1", "threadId": "thread-1", "turnId": turn_id, "tool": "linear_graphql", "arguments": {"query": "query A { viewer { id } }"}}})
            result = json.loads(sys.stdin.readline())
            record(result)
            send({"method": "turn/completed", "params": {"threadId": "thread-1", "turn": {"id": turn_id, "items": [], "status": "completed"}}})
        elif mode == "turn_timeout":
            time.sleep(2)
        elif mode == "exit_during_turn":
            sys.exit(9)
    elif method == "shutdown":
        sys.exit(0)
"""


class CodexAgentRunnerTests(unittest.TestCase):
    def build_runner(self, root: Path, mode: str, *, read_timeout_ms: int = 1000, turn_timeout_ms: int = 1000, client_tools=None):
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
        return CodexAgentRunner(cfg, client_tools=client_tools), workspace, record

    def test_protocol_success_launches_in_workspace_and_streams_events(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner, workspace, record = self.build_runner(root, "success")
            events = []

            result = runner.run_turn(issue(), "Do the work", workspace, on_event=events.append)

            self.assertTrue(result.success)
            self.assertEqual(result.session_id, "thread-1-turn-1")
            self.assertEqual([event["event"] for event in events], ["session_started", "notification", "thread/tokenUsage/updated", "account/rateLimits/updated", "turn_completed"])
            self.assertEqual(events[0]["thread_id"], "thread-1")
            self.assertEqual(events[0]["turn_id"], "turn-1")
            self.assertEqual(events[3]["rateLimits"], {"primary": {"remaining": 10}})
            records = json.loads(record.read_text(encoding="utf-8"))
            self.assertEqual([message["method"] for message in records[:4]], ["initialize", "thread/start", "thread/name/set", "turn/start"])
            self.assertEqual(records[0]["params"]["clientInfo"]["name"], "harness-runtime")
            self.assertEqual(records[0]["params"]["clientInfo"]["version"], "1.3.1")
            self.assertEqual(records[1]["params"]["cwd"], str(workspace.resolve()))
            self.assertEqual(records[1]["params"]["approvalPolicy"], "on-request")
            self.assertEqual(records[1]["params"]["sandbox"], "workspace-write")
            self.assertEqual(records[2]["params"]["name"], "ABC-1: Test issue")
            self.assertEqual(records[3]["params"]["input"], [{"type": "text", "text": "Do the work"}])
            self.assertEqual(records[3]["params"]["threadId"], "thread-1")
            self.assertEqual(records[3]["params"]["sandboxPolicy"], {"type": "workspaceWrite"})

    def test_protocol_continuation_turns_reuse_thread_and_send_continuation_prompt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner, workspace, record = self.build_runner(root, "multi_turn")
            decisions = []

            result = runner.run_session(
                issue(),
                "Do the work",
                "Continue from prior work",
                workspace,
                attempt=4,
                max_turns=3,
                should_continue=lambda completed_turns: decisions.append(completed_turns) or completed_turns < 2,
            )

            self.assertTrue(result.success)
            self.assertEqual(result.session_id, "thread-1-turn-2")
            self.assertEqual(result.turn_count, 2)
            self.assertEqual(decisions, [1, 2])
            records = json.loads(record.read_text(encoding="utf-8"))
            turn_starts = [message for message in records if message.get("method") == "turn/start"]
            self.assertEqual(len(turn_starts), 2)
            self.assertEqual(turn_starts[0]["params"]["threadId"], "thread-1")
            self.assertEqual(turn_starts[1]["params"]["threadId"], "thread-1")
            self.assertEqual(turn_starts[0]["params"]["input"], [{"type": "text", "text": "Do the work"}])
            self.assertEqual(turn_starts[1]["params"]["input"], [{"type": "text", "text": "Continue from prior work"}])

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

    def test_protocol_auto_approves_and_handles_supported_and_unsupported_tool_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner, workspace, record = self.build_runner(
                root,
                "approval_tools",
                client_tools={"echo": lambda arguments: {"echoed": arguments}},
            )
            events = []

            runner.run_turn(issue(), "Do the work", workspace, on_event=events.append)

            names = [event["event"] for event in events]
            self.assertIn("approval_auto_approved", names)
            self.assertIn("approval_auto_resolved", names)
            self.assertIn("unsupported_tool_call", names)
            self.assertIn("client_tool_completed", names)
            records = json.loads(record.read_text(encoding="utf-8"))
            approval_response = next(message for message in records if message.get("id") == "approval-1")
            self.assertEqual(approval_response["result"]["decision"], "acceptForSession")
            permissions_response = next(message for message in records if message.get("id") == "permissions-1")
            self.assertEqual(permissions_response["result"]["permissions"], {"fileSystem": None, "network": None})
            tool_results = [message for message in records if message.get("id") in {"tool-unsupported", "tool-supported"}]
            self.assertEqual(tool_results[0]["id"], "tool-unsupported")
            self.assertFalse(tool_results[0]["result"]["success"])
            self.assertEqual(json.loads(tool_results[0]["result"]["contentItems"][0]["text"]), {"error": "unsupported_tool_call"})
            self.assertEqual(tool_results[1]["id"], "tool-supported")
            self.assertTrue(tool_results[1]["result"]["success"])
            self.assertEqual(json.loads(tool_results[1]["result"]["contentItems"][0]["text"]), {"echoed": {"value": 2}})

    def test_protocol_does_not_send_non_schema_tool_advertisement_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner, workspace, record = self.build_runner(
                root,
                "linear_graphql",
                client_tools={"linear_graphql": lambda arguments: ClientToolResult(True, {"data": {"ok": True}})},
            )

            runner.run_turn(issue(), "Do the work", workspace)

            records = json.loads(record.read_text(encoding="utf-8"))
            startup = [message for message in records if message.get("method") in {"initialize", "thread/start", "turn/start"}]
            self.assertTrue(startup)
            for message in startup:
                params = message.get("params", {})
                self.assertNotIn("client_tools", params)
                self.assertNotIn("clientTools", params)
                self.assertNotIn("tools", params)
                self.assertNotIn("dynamicTools", params)

    def test_protocol_returns_successful_linear_graphql_result_when_requested(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner, workspace, record = self.build_runner(
                root,
                "linear_graphql",
                client_tools={"linear_graphql": lambda arguments: ClientToolResult(True, {"data": {"ok": True}, "arguments": arguments})},
            )
            events = []

            runner.run_turn(issue(), "Do the work", workspace, on_event=events.append)

            records = json.loads(record.read_text(encoding="utf-8"))
            tool_result = next(message for message in records if message.get("id") == "linear-1")
            self.assertTrue(tool_result["result"]["success"])
            self.assertEqual(json.loads(tool_result["result"]["contentItems"][0]["text"])["data"], {"ok": True})
            self.assertIn("client_tool_completed", [event["event"] for event in events])

    def test_protocol_returns_failed_linear_graphql_result(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner, workspace, record = self.build_runner(
                root,
                "linear_graphql",
                client_tools={"linear_graphql": lambda arguments: ClientToolResult(False, {"error": "invalid_query"})},
            )
            events = []

            runner.run_turn(issue(), "Do the work", workspace, on_event=events.append)

            records = json.loads(record.read_text(encoding="utf-8"))
            tool_result = next(message for message in records if message.get("id") == "linear-1")
            self.assertFalse(tool_result["result"]["success"])
            self.assertEqual(json.loads(tool_result["result"]["contentItems"][0]["text"]), {"error": "invalid_query"})
            self.assertIn("client_tool_failed", [event["event"] for event in events])

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
