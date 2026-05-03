"""Codex app-server runner abstraction with hardened defaults."""

from __future__ import annotations

import json
import queue
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from .client_tools import ClientToolResult
from .models import Issue, RuntimeConfig
from .workspace import ensure_contained


class AgentRunnerError(RuntimeError):
    pass


@dataclass(frozen=True)
class AgentRunResult:
    success: bool
    session_id: str | None = None
    error: str | None = None
    turn_count: int = 0
    events: tuple[dict[str, Any], ...] = ()


AgentEventCallback = Callable[[dict[str, Any]], None]
ClientToolHandler = Callable[[Any], Any]
ContinuationCallback = Callable[[int], bool]


class CodexAgentRunner:
    """Hardened stdio JSON-lines app-server client.

    SPEC.md intentionally does not define the exact Codex protocol schema. This
    client keeps that schema behind a small JSON-RPC-style adapter so the
    orchestrator owns policy while protocol envelopes can evolve in one place.
    """

    def __init__(self, config: RuntimeConfig, client_tools: Mapping[str, ClientToolHandler] | None = None):
        self.config = config
        self.client_tools = dict(client_tools or {})

    def run_turn(
        self,
        issue: Issue,
        prompt: str,
        workspace_path: Path,
        attempt: int | None = None,
        on_event: AgentEventCallback | None = None,
    ) -> AgentRunResult:
        return self.run_session(
            issue,
            prompt,
            "Continue working on this issue. Inspect the current workspace state and proceed with the next useful step.",
            workspace_path,
            attempt=attempt,
            max_turns=1,
            should_continue=lambda completed_turns: False,
            on_event=on_event,
        )

    def run_session(
        self,
        issue: Issue,
        prompt: str,
        continuation_prompt: str,
        workspace_path: Path,
        attempt: int | None = None,
        *,
        max_turns: int,
        should_continue: ContinuationCallback,
        on_event: AgentEventCallback | None = None,
    ) -> AgentRunResult:
        workspace_path = workspace_path.resolve()
        ensure_contained(self.config.workspace_root, workspace_path)
        events: list[dict[str, Any]] = []
        process: subprocess.Popen[str] | None = None
        session_id: str | None = None
        completed_turns = 0

        def emit(event: Mapping[str, Any]) -> None:
            normalized = dict(event)
            normalized.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
            if process is not None:
                normalized.setdefault("codex_app_server_pid", process.pid)
            events.append(normalized)
            if on_event is not None:
                on_event(normalized)

        try:
            process = subprocess.Popen(
                ["bash", "-lc", self.config.codex_command],
                cwd=workspace_path,
                text=True,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=1,
            )
        except FileNotFoundError as exc:
            raise AgentRunnerError("codex_not_found") from exc

        client = _JsonLineAppServerClient(
            process,
            config=self.config,
            client_tools=self.client_tools,
            read_timeout_ms=self.config.codex_read_timeout_ms,
            turn_timeout_ms=self.config.codex_turn_timeout_ms,
            emit=emit,
        )
        try:
            client.initialize(workspace_path)
            thread_id = client.create_thread(issue, workspace_path)
            while completed_turns < max(max_turns, 1):
                current_prompt = prompt if completed_turns == 0 else continuation_prompt
                turn_id = client.start_turn(issue, current_prompt, workspace_path, thread_id, attempt)
                session_id = f"{thread_id}-{turn_id}"
                emit(
                    {
                        "event": "session_started",
                        "session_id": session_id,
                        "thread_id": thread_id,
                        "turn_id": turn_id,
                        "turn_index": completed_turns + 1,
                        "message": f"{issue.identifier}: {issue.title}",
                    }
                )
                client.stream_turn(turn_id)
                completed_turns += 1
                if completed_turns >= max(max_turns, 1):
                    break
                if not should_continue(completed_turns):
                    break
        finally:
            client.close()
        return AgentRunResult(success=True, session_id=session_id, turn_count=completed_turns, events=tuple(events))


class _JsonLineAppServerClient:
    def __init__(
        self,
        process: subprocess.Popen[str],
        *,
        config: RuntimeConfig,
        client_tools: Mapping[str, ClientToolHandler],
        read_timeout_ms: int,
        turn_timeout_ms: int,
        emit: AgentEventCallback,
    ):
        self.process = process
        self.config = config
        self.client_tools = dict(client_tools)
        self.read_timeout_ms = read_timeout_ms
        self.turn_timeout_ms = turn_timeout_ms
        self.emit = emit
        self._next_id = 1
        self._messages: queue.Queue[tuple[str, str]] = queue.Queue()
        self._stderr: list[str] = []
        self._start_reader("stdout", process.stdout)
        self._start_reader("stderr", process.stderr)

    def initialize(self, workspace_path: Path) -> None:
        self.request(
            "initialize",
            {
                "clientInfo": {
                    "name": "harness-runtime",
                    "title": "Harness Hardened Symphony Runtime",
                    "version": "1.4.1",
                },
                "capabilities": {
                    "experimentalApi": True,
                },
            },
            timeout_ms=self.read_timeout_ms,
        )

    def create_thread(self, issue: Issue, workspace_path: Path) -> str:
        result = self.request(
            "thread/start",
            {
                "cwd": str(workspace_path),
                "approvalPolicy": self.config.approval_policy,
                "sandbox": self.config.thread_sandbox,
                "serviceName": "harness-runtime",
                "ephemeral": True,
            },
            timeout_ms=self.read_timeout_ms,
        )
        thread_id = _extract_identifier(result, ("thread_id", "threadId", "id"), nested=("thread", "session"))
        self.request(
            "thread/name/set",
            {
                "threadId": thread_id,
                "name": f"{issue.identifier}: {issue.title}",
            },
            timeout_ms=self.read_timeout_ms,
        )
        return thread_id

    def start_turn(self, issue: Issue, prompt: str, workspace_path: Path, thread_id: str, attempt: int | None) -> str:
        result = self.request(
            "turn/start",
            {
                "threadId": thread_id,
                "cwd": str(workspace_path),
                "input": [{"type": "text", "text": prompt}],
                "approvalPolicy": self.config.approval_policy,
                "sandboxPolicy": _sandbox_policy(self.config.turn_sandbox_policy),
            },
            timeout_ms=self.read_timeout_ms,
        )
        return _extract_identifier(result, ("turn_id", "turnId", "id"), nested=("turn",))

    def stream_turn(self, turn_id: str) -> None:
        deadline = time.monotonic() + self.turn_timeout_ms / 1000
        while True:
            message = self.read_message(deadline=deadline, timeout_error="turn_timeout")
            event = _event_from_message(message)
            if event is None:
                continue
            event.setdefault("turn_id", turn_id)
            self.emit(event)
            if self.handle_policy_event(event):
                continue
            name = str(event.get("event") or "")
            if name == "turn_completed":
                return
            if name == "turn_failed":
                raise AgentRunnerError("turn_failed")
            if name == "turn_cancelled":
                raise AgentRunnerError("turn_cancelled")
            if name == "turn_input_required":
                raise AgentRunnerError("turn_input_required")
            if name == "turn_ended_with_error":
                raise AgentRunnerError("turn_failed")
            if name == "startup_failed":
                raise AgentRunnerError("response_error")

    def handle_policy_event(self, event: Mapping[str, Any]) -> bool:
        name = str(event.get("event") or "")
        if name in {"approval_requested", "command_approval_requested", "file_change_approval_requested"}:
            self.respond_to_approval(event)
            self.emit({"event": "approval_auto_approved", "approval_id": _event_identifier(event), "message": "approved by runtime policy"})
            return True
        if name == "permissions_approval_requested":
            self.respond_to_permissions_request(event)
            self.emit({"event": "approval_auto_resolved", "approval_id": _event_identifier(event), "message": "no additional permissions granted by runtime policy"})
            return True
        if name == "turn_input_required":
            self.respond_to_user_input(event)
            return False
        if name in {"tool_call", "client_tool_call"}:
            self.respond_to_tool_call(event)
            return True
        return False

    def respond_to_approval(self, event: Mapping[str, Any]) -> None:
        self.write_response(_request_id(event), {"decision": "acceptForSession"})

    def respond_to_permissions_request(self, event: Mapping[str, Any]) -> None:
        self.write_response(_request_id(event), {"permissions": {"fileSystem": None, "network": None}, "scope": "turn"})

    def respond_to_user_input(self, event: Mapping[str, Any]) -> None:
        request_id = _request_id(event)
        if request_id is not None:
            self.write_response(request_id, {"answers": {}})

    def respond_to_tool_call(self, event: Mapping[str, Any]) -> None:
        tool_name = _tool_name(event)
        call_id = _event_identifier(event)
        if tool_name not in self.client_tools:
            self.write_response(_request_id(event), _tool_result(False, {"error": "unsupported_tool_call"}))
            self.emit({"event": "unsupported_tool_call", "tool_name": tool_name, "tool_call_id": call_id})
            return
        try:
            result = self.client_tools[tool_name](_tool_arguments(event))
        except Exception as exc:
            self.write_response(_request_id(event), _tool_result(False, {"error": str(exc)}))
            self.emit({"event": "client_tool_failed", "tool_name": tool_name, "tool_call_id": call_id, "message": str(exc)})
            return
        if isinstance(result, ClientToolResult):
            success = result.success
            output = result.output
        else:
            success = True
            output = result
        self.write_response(_request_id(event), _tool_result(success, output))
        event_name = "client_tool_completed" if success else "client_tool_failed"
        self.emit({"event": event_name, "tool_name": tool_name, "tool_call_id": call_id})

    def request(self, method: str, params: Mapping[str, Any], *, timeout_ms: int) -> Mapping[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        self.write_message({"jsonrpc": "2.0", "id": request_id, "method": method, "params": dict(params)})
        deadline = time.monotonic() + timeout_ms / 1000
        while True:
            message = self.read_message(deadline=deadline, timeout_error="response_timeout")
            event = _event_from_message(message)
            if event is not None:
                self.emit(event)
                self.handle_policy_event(event)
                continue
            if message.get("id") != request_id:
                continue
            if message.get("error"):
                raise AgentRunnerError("response_error")
            result = message.get("result")
            if not isinstance(result, Mapping):
                raise AgentRunnerError("response_error")
            return result

    def write_message(self, message: Mapping[str, Any]) -> None:
        if self.process.stdin is None:
            raise AgentRunnerError("port_exit")
        try:
            self.process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
            self.process.stdin.flush()
        except BrokenPipeError as exc:
            raise AgentRunnerError("port_exit") from exc

    def write_response(self, request_id: object | None, result: Mapping[str, Any]) -> None:
        if request_id is None:
            raise AgentRunnerError("response_error")
        self.write_message({"jsonrpc": "2.0", "id": request_id, "result": dict(result)})

    def read_message(self, *, deadline: float, timeout_error: str) -> Mapping[str, Any]:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AgentRunnerError(timeout_error)
            if self.process.poll() is not None and self._messages.empty():
                raise AgentRunnerError("port_exit")
            try:
                source, line = self._messages.get(timeout=remaining)
            except queue.Empty as exc:
                if self.process.poll() is not None:
                    raise AgentRunnerError("port_exit") from exc
                raise AgentRunnerError(timeout_error) from exc
            if source == "stderr":
                self._stderr.append(line)
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                self.emit({"event": "malformed", "message": line})
                continue
            if not isinstance(message, Mapping):
                self.emit({"event": "malformed", "message": line})
                continue
            return message

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=1)
        for pipe in (self.process.stdin, self.process.stdout, self.process.stderr):
            if pipe is not None and not pipe.closed:
                pipe.close()

    def _start_reader(self, source: str, pipe) -> None:
        if pipe is None:
            return

        def read_lines() -> None:
            for line in pipe:
                self._messages.put((source, line.rstrip("\n")))

        thread = threading.Thread(target=read_lines, daemon=True)
        thread.start()


def _event_from_message(message: Mapping[str, Any]) -> dict[str, Any] | None:
    if "event" in message:
        return dict(message)
    method = message.get("method")
    params = message.get("params")
    if method == "thread/tokenUsage/updated" and isinstance(params, Mapping):
        event = dict(params)
        event["event"] = "thread/tokenUsage/updated"
        total = _nested_mapping(params, ("tokenUsage", "total"))
        if total:
            event["usage"] = total
        return event
    if method == "account/rateLimits/updated" and isinstance(params, Mapping):
        event = dict(params)
        event["event"] = "account/rateLimits/updated"
        return event
    if method == "turn/completed" and isinstance(params, Mapping):
        event = dict(params)
        event["event"] = "turn_completed"
        event["thread_id"] = params.get("threadId")
        event["turn_id"] = _extract_turn_id_from_params(params)
        return event
    if method == "turn/started" and isinstance(params, Mapping):
        event = dict(params)
        event["event"] = "turn_started"
        event["thread_id"] = params.get("threadId")
        event["turn_id"] = _extract_turn_id_from_params(params)
        return event
    if method == "error" and isinstance(params, Mapping):
        event = dict(params)
        event["event"] = "turn_failed"
        event["thread_id"] = params.get("threadId")
        event["turn_id"] = params.get("turnId")
        error = params.get("error")
        if isinstance(error, Mapping):
            event["message"] = error.get("message")
        return event
    if method in {"item/commandExecution/requestApproval", "item/fileChange/requestApproval"} and isinstance(params, Mapping):
        event = dict(params)
        event.update(
            {
                "event": "command_approval_requested" if method == "item/commandExecution/requestApproval" else "file_change_approval_requested",
                "_request_id": message.get("id"),
            }
        )
        return event
    if method == "item/tool/requestUserInput" and isinstance(params, Mapping):
        event = dict(params)
        event.update({"event": "turn_input_required", "_request_id": message.get("id")})
        return event
    if method == "item/permissions/requestApproval" and isinstance(params, Mapping):
        event = dict(params)
        event.update({"event": "permissions_approval_requested", "_request_id": message.get("id")})
        return event
    if method == "item/tool/call" and isinstance(params, Mapping):
        event = dict(params)
        event.update(
            {
                "event": "client_tool_call",
                "tool_name": params.get("tool"),
                "tool_call_id": params.get("callId"),
                "_request_id": message.get("id"),
            }
        )
        return event
    if method in {"event", "notification"} and isinstance(params, Mapping):
        event = dict(params)
        event.setdefault("event", method)
        return event
    return None


def _nested_mapping(mapping: Mapping[str, Any], path: tuple[str, ...]) -> Mapping[str, Any] | None:
    current: Any = mapping
    for key in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current if isinstance(current, Mapping) else None


def _extract_turn_id_from_params(params: Mapping[str, Any]) -> str | None:
    turn = params.get("turn")
    if isinstance(turn, Mapping) and turn.get("id"):
        return str(turn["id"])
    turn_id = params.get("turnId")
    return str(turn_id) if turn_id else None


def _extract_identifier(result: Mapping[str, Any], keys: tuple[str, ...], *, nested: tuple[str, ...]) -> str:
    for key in keys:
        value = result.get(key)
        if value:
            return str(value)
    for nested_key in nested:
        value = result.get(nested_key)
        if isinstance(value, Mapping):
            for key in keys:
                identifier = value.get(key)
                if identifier:
                    return str(identifier)
    raise AgentRunnerError("response_error")


def _event_identifier(event: Mapping[str, Any]) -> str | None:
    for key in ("id", "approval_id", "approvalId", "tool_call_id", "toolCallId", "call_id", "callId", "itemId"):
        value = event.get(key)
        if value:
            return str(value)
    payload = event.get("payload")
    if isinstance(payload, Mapping):
        for key in ("id", "approval_id", "approvalId", "tool_call_id", "toolCallId", "call_id", "callId", "itemId"):
            value = payload.get(key)
            if value:
                return str(value)
    return None


def _request_id(event: Mapping[str, Any]) -> object | None:
    return event.get("_request_id")


def _tool_name(event: Mapping[str, Any]) -> str | None:
    for key in ("tool_name", "toolName", "name", "tool"):
        value = event.get(key)
        if value:
            return str(value)
    payload = event.get("payload")
    if isinstance(payload, Mapping):
        for key in ("tool_name", "toolName", "name", "tool"):
            value = payload.get(key)
            if value:
                return str(value)
    return None


def _tool_arguments(event: Mapping[str, Any]) -> Any:
    for key in ("arguments", "args", "input"):
        if key in event:
            return event[key]
    payload = event.get("payload")
    if isinstance(payload, Mapping):
        for key in ("arguments", "args", "input"):
            if key in payload:
                return payload[key]
    return {}


def _tool_result(success: bool, output: Any) -> dict[str, Any]:
    return {
        "contentItems": [{"type": "inputText", "text": _tool_output_text(output)}],
        "success": success,
    }


def _tool_output_text(output: Any) -> str:
    if isinstance(output, str):
        return output
    return json.dumps(output, sort_keys=True)


def _sandbox_policy(value: str) -> dict[str, Any]:
    normalized = value.strip().lower()
    if normalized in {"workspace-write", "workspacewrite"}:
        return {"type": "workspaceWrite"}
    if normalized in {"read-only", "readonly"}:
        return {"type": "readOnly"}
    if normalized in {"danger-full-access", "dangerfullaccess"}:
        return {"type": "dangerFullAccess"}
    return {"type": "workspaceWrite"}
