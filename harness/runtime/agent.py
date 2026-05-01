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
    events: tuple[dict[str, Any], ...] = ()


AgentEventCallback = Callable[[dict[str, Any]], None]
ClientToolHandler = Callable[[Any], Any]


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
        workspace_path = workspace_path.resolve()
        ensure_contained(self.config.workspace_root, workspace_path)
        events: list[dict[str, Any]] = []
        process: subprocess.Popen[str] | None = None

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
            turn_id = client.start_turn(issue, prompt, workspace_path, thread_id, attempt)
            session_id = f"{thread_id}-{turn_id}"
            emit(
                {
                    "event": "session_started",
                    "session_id": session_id,
                    "thread_id": thread_id,
                    "turn_id": turn_id,
                    "message": f"{issue.identifier}: {issue.title}",
                }
            )
            client.stream_turn(turn_id)
        finally:
            client.close()
        return AgentRunResult(success=True, session_id=session_id, events=tuple(events))


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
                "cwd": str(workspace_path),
                "approval_policy": self.config.approval_policy,
                "thread_sandbox": self.config.thread_sandbox,
                "turn_sandbox_policy": self.config.turn_sandbox_policy,
                "client_tools": [{"name": name} for name in sorted(self.client_tools)],
            },
            timeout_ms=self.read_timeout_ms,
        )

    def create_thread(self, issue: Issue, workspace_path: Path) -> str:
        result = self.request(
            "thread/create",
            {
                "cwd": str(workspace_path),
                "title": f"{issue.identifier}: {issue.title}",
                "metadata": {
                    "issue_id": issue.id,
                    "issue_identifier": issue.identifier,
                    "issue_url": issue.url,
                },
            },
            timeout_ms=self.read_timeout_ms,
        )
        return _extract_identifier(result, ("thread_id", "threadId", "id"), nested=("thread", "session"))

    def start_turn(self, issue: Issue, prompt: str, workspace_path: Path, thread_id: str, attempt: int | None) -> str:
        result = self.request(
            "turn/start",
            {
                "thread_id": thread_id,
                "cwd": str(workspace_path),
                "prompt": prompt,
                "approval_policy": self.config.approval_policy,
                "sandbox_policy": self.config.turn_sandbox_policy,
                "title": f"{issue.identifier}: {issue.title}",
                "metadata": {
                    "issue_id": issue.id,
                    "issue_identifier": issue.identifier,
                    "attempt": attempt,
                },
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
        if name in {"tool_call", "client_tool_call"}:
            self.respond_to_tool_call(event)
            return True
        return False

    def respond_to_approval(self, event: Mapping[str, Any]) -> None:
        self.write_message(
            {
                "jsonrpc": "2.0",
                "method": "approval/respond",
                "params": {
                    "approval_id": _event_identifier(event),
                    "approved": True,
                    "reason": "auto-approved by runtime policy",
                },
            }
        )

    def respond_to_tool_call(self, event: Mapping[str, Any]) -> None:
        tool_name = _tool_name(event)
        call_id = _event_identifier(event)
        if tool_name not in self.client_tools:
            self.write_message(_tool_result(call_id, tool_name, False, {"error": "unsupported_tool_call"}))
            self.emit({"event": "unsupported_tool_call", "tool_name": tool_name, "tool_call_id": call_id})
            return
        try:
            result = self.client_tools[tool_name](_tool_arguments(event))
        except Exception as exc:
            self.write_message(_tool_result(call_id, tool_name, False, {"error": str(exc)}))
            self.emit({"event": "client_tool_failed", "tool_name": tool_name, "tool_call_id": call_id, "message": str(exc)})
            return
        if isinstance(result, ClientToolResult):
            success = result.success
            output = result.output
        else:
            success = True
            output = result
        self.write_message(_tool_result(call_id, tool_name, success, output))
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
            try:
                self.write_message({"jsonrpc": "2.0", "method": "shutdown", "params": {}})
            except AgentRunnerError:
                pass
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
    if method in {"event", "notification"} and isinstance(params, Mapping):
        event = dict(params)
        event.setdefault("event", method)
        return event
    return None


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
    for key in ("id", "approval_id", "approvalId", "tool_call_id", "toolCallId", "call_id", "callId"):
        value = event.get(key)
        if value:
            return str(value)
    payload = event.get("payload")
    if isinstance(payload, Mapping):
        for key in ("id", "approval_id", "approvalId", "tool_call_id", "toolCallId", "call_id", "callId"):
            value = payload.get(key)
            if value:
                return str(value)
    return None


def _tool_name(event: Mapping[str, Any]) -> str | None:
    for key in ("tool_name", "toolName", "name"):
        value = event.get(key)
        if value:
            return str(value)
    payload = event.get("payload")
    if isinstance(payload, Mapping):
        for key in ("tool_name", "toolName", "name"):
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


def _tool_result(call_id: str | None, tool_name: str | None, success: bool, output: Any) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "method": "tool/result",
        "params": {
            "tool_call_id": call_id,
            "tool_name": tool_name,
            "success": success,
            "output": output,
        },
    }
