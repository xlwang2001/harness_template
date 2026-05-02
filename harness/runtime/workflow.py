"""Workflow loading and hardened config resolution."""

from __future__ import annotations

import ast
import hashlib
import os
import tempfile
from pathlib import Path
from typing import Any

from .models import RuntimeConfig, WorkflowDefinition


class WorkflowError(ValueError):
    code = "workflow_error"


class MissingWorkflowFile(WorkflowError):
    code = "missing_workflow_file"


class WorkflowParseError(WorkflowError):
    code = "workflow_parse_error"


class WorkflowFrontMatterNotMap(WorkflowError):
    code = "workflow_front_matter_not_a_map"


class ConfigValidationError(WorkflowError):
    code = "config_validation_error"


class WorkflowReloader:
    """Track workflow changes while preserving the last known good config."""

    def __init__(self, path: Path | None = None, *, cwd: Path | None = None):
        self.path = path
        self.cwd = cwd
        self.last_signature: WorkflowFileSignature | None = None
        self.last_good: tuple[WorkflowDefinition, RuntimeConfig] | None = None
        self.last_error: Exception | None = None

    def load_initial(self) -> tuple[WorkflowDefinition, RuntimeConfig]:
        workflow, config = self._load()
        self.last_good = (workflow, config)
        self.last_signature = WorkflowFileSignature.from_path(workflow.path)
        self.last_error = None
        return workflow, config

    def reload_if_changed(self) -> tuple[WorkflowDefinition, RuntimeConfig] | None:
        workflow_path = self._workflow_path()
        try:
            signature = WorkflowFileSignature.from_path(workflow_path)
        except OSError as exc:
            self.last_error = exc
            return None
        if self.last_signature == signature:
            return None
        try:
            workflow, config = self._load()
        except Exception as exc:
            self.last_error = exc
            return None
        self.last_good = (workflow, config)
        self.last_signature = signature
        self.last_error = None
        return workflow, config

    def _load(self) -> tuple[WorkflowDefinition, RuntimeConfig]:
        workflow = load_workflow(self.path, cwd=self.cwd)
        config = resolve_config(workflow)
        validate_dispatch_config(config)
        return workflow, config

    def _workflow_path(self) -> Path:
        base = self.cwd or Path.cwd()
        workflow_path = (self.path or base / "WORKFLOW.md").expanduser()
        if not workflow_path.is_absolute():
            workflow_path = (base / workflow_path).resolve()
        return workflow_path


class WorkflowFileSignature(tuple):
    """mtime/size/hash signature used to catch missed timestamp-only changes."""

    __slots__ = ()

    def __new__(cls, mtime_ns: int, size: int, sha256: str):
        return super().__new__(cls, (mtime_ns, size, sha256))

    @classmethod
    def from_path(cls, path: Path) -> "WorkflowFileSignature":
        stat = path.stat()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return cls(stat.st_mtime_ns, stat.st_size, digest)


def load_workflow(path: Path | None = None, *, cwd: Path | None = None) -> WorkflowDefinition:
    base = cwd or Path.cwd()
    workflow_path = (path or base / "WORKFLOW.md").expanduser()
    if not workflow_path.is_absolute():
        workflow_path = (base / workflow_path).resolve()
    if not workflow_path.is_file():
        raise MissingWorkflowFile(f"workflow file not found: {workflow_path}")
    text = workflow_path.read_text(encoding="utf-8")
    config, body = split_front_matter(text)
    return WorkflowDefinition(path=workflow_path, config=config, prompt_template=body.strip())


def split_front_matter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end == -1:
        raise WorkflowParseError("unterminated workflow front matter")
    raw = text[4:end].strip()
    body = text[end + 4 :]
    if not raw:
        return {}, body
    config = parse_simple_yaml(raw)
    if not isinstance(config, dict):
        raise WorkflowFrontMatterNotMap("workflow front matter must be a map")
    return config, body


def parse_simple_yaml(raw: str) -> dict[str, Any]:
    """Parse the workflow YAML subset used by scaffold templates.

    The runtime remains standard-library first. This parser supports nested maps,
    lists, quoted strings, integers, and block scalars, and raises for shapes it
    cannot parse instead of guessing.
    """

    root: dict[str, Any] = {}
    stack: list[tuple[int, Any]] = [(-1, root)]
    lines = raw.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip() or line.lstrip().startswith("#"):
            index += 1
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if stripped.startswith("- "):
            if not isinstance(parent, list):
                raise WorkflowParseError(f"list item without list parent: {line}")
            parent.append(_parse_scalar(stripped[2:].strip()))
            index += 1
            continue
        if ":" not in stripped:
            raise WorkflowParseError(f"expected key/value line: {line}")
        key, value = stripped.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            raise WorkflowParseError(f"empty key in line: {line}")
        if value == "|":
            block_lines: list[str] = []
            index += 1
            while index < len(lines):
                block = lines[index]
                block_indent = len(block) - len(block.lstrip(" "))
                if block.strip() and block_indent <= indent:
                    break
                block_lines.append(block[indent + 2 :] if len(block) >= indent + 2 else "")
                index += 1
            parent[key] = "\n".join(block_lines).rstrip()
            continue
        if value:
            parent[key] = _parse_scalar(value)
            index += 1
            continue
        next_kind = _peek_container_kind(lines, index + 1, indent)
        child: dict[str, Any] | list[Any] = [] if next_kind == "list" else {}
        parent[key] = child
        stack.append((indent, child))
        index += 1
    return root


def resolve_config(workflow: WorkflowDefinition) -> RuntimeConfig:
    config = workflow.config
    tracker = _map(config.get("tracker"))
    polling = _map(config.get("polling"))
    workspace = _map(config.get("workspace"))
    hooks = _map(config.get("hooks"))
    agent = _map(config.get("agent"))
    codex = _map(config.get("codex"))
    logging_config = _map(config.get("logging"))
    runtime_state = _map(config.get("runtime_state"))
    raw_server = config.get("server")
    server = _map(raw_server)
    server_port_present = isinstance(raw_server, dict) and "port" in raw_server
    runtime_state_file = _optional_resolved_path(runtime_state.get("file"), workflow.path.parent)

    tracker_kind = str(tracker.get("kind") or "linear")
    if tracker_kind != "linear":
        raise ConfigValidationError(f"unsupported tracker kind: {tracker_kind}")

    api_key = _resolve_env_value(tracker.get("api_key") or "$LINEAR_API_KEY")
    project_slug = _resolve_env_value(tracker.get("project_slug"))
    workspace_root = _resolve_path(
        workspace.get("root") or str(Path(tempfile.gettempdir()) / "symphony_workspaces"),
        workflow.path.parent,
    )

    return RuntimeConfig(
        workflow_path=workflow.path,
        tracker_kind=tracker_kind,
        tracker_endpoint=str(tracker.get("endpoint") or "https://api.linear.app/graphql"),
        tracker_api_key=api_key,
        tracker_project_slug=project_slug,
        active_states=tuple(_list(tracker.get("active_states"), ["Todo", "In Progress"])),
        terminal_states=tuple(_list(tracker.get("terminal_states"), ["Closed", "Cancelled", "Canceled", "Duplicate", "Done"])),
        polling_interval_ms=_positive_int(polling.get("interval_ms"), 30000, "polling.interval_ms"),
        workspace_root=workspace_root,
        hooks={
            "after_create": _optional_str(hooks.get("after_create")),
            "before_run": _optional_str(hooks.get("before_run")),
            "after_run": _optional_str(hooks.get("after_run")),
            "before_remove": _optional_str(hooks.get("before_remove")),
        },
        hooks_timeout_ms=_positive_int(hooks.get("timeout_ms"), 60000, "hooks.timeout_ms"),
        max_concurrent_agents=_positive_int(agent.get("max_concurrent_agents"), 10, "agent.max_concurrent_agents"),
        max_turns=_positive_int(agent.get("max_turns"), 20, "agent.max_turns"),
        max_retry_backoff_ms=_positive_int(agent.get("max_retry_backoff_ms"), 300000, "agent.max_retry_backoff_ms"),
        max_concurrent_agents_by_state=_state_limits(agent.get("max_concurrent_agents_by_state")),
        codex_command=str(codex.get("command") or "codex app-server"),
        codex_turn_timeout_ms=_positive_int(codex.get("turn_timeout_ms"), 3600000, "codex.turn_timeout_ms"),
        codex_read_timeout_ms=_positive_int(codex.get("read_timeout_ms"), 5000, "codex.read_timeout_ms"),
        codex_stall_timeout_ms=_int(codex.get("stall_timeout_ms"), 300000, "codex.stall_timeout_ms"),
        approval_policy=str(codex.get("approval_policy") or "on-request"),
        thread_sandbox=str(codex.get("thread_sandbox") or "workspace-write"),
        turn_sandbox_policy=str(codex.get("turn_sandbox_policy") or "workspace-write"),
        server_enabled=_bool(server.get("enabled"), False) or server_port_present,
        server_host=str(server.get("host") or "127.0.0.1"),
        server_port=_nonnegative_int(server.get("port"), 8765, "server.port"),
        logging_level=_logging_level(logging_config.get("level")),
        logging_console=_bool(logging_config.get("console"), True),
        logging_file=_optional_resolved_path(logging_config.get("file"), workflow.path.parent),
        runtime_state_file=runtime_state_file,
        runtime_state_persist_retries=_bool(runtime_state.get("persist_retries"), runtime_state_file is not None),
        runtime_state_persist_sessions=_bool(runtime_state.get("persist_sessions"), runtime_state_file is not None),
    )


def validate_dispatch_config(config: RuntimeConfig) -> None:
    if config.tracker_kind != "linear":
        raise ConfigValidationError(f"unsupported tracker kind: {config.tracker_kind}")
    if not config.tracker_api_key:
        raise ConfigValidationError("tracker.api_key is required after environment resolution")
    if not config.tracker_project_slug:
        raise ConfigValidationError("tracker.project_slug is required for Linear")
    if not config.codex_command.strip():
        raise ConfigValidationError("codex.command is required")


def _peek_container_kind(lines: list[str], start: int, parent_indent: int) -> str:
    for next_line in lines[start:]:
        if not next_line.strip() or next_line.lstrip().startswith("#"):
            continue
        indent = len(next_line) - len(next_line.lstrip(" "))
        if indent <= parent_indent:
            return "map"
        return "list" if next_line.strip().startswith("- ") else "map"
    return "map"


def _parse_scalar(value: str) -> Any:
    if value in {"null", "None", "~"}:
        return None
    if value in {"true", "True"}:
        return True
    if value in {"false", "False"}:
        return False
    try:
        return int(value)
    except ValueError:
        pass
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        try:
            return ast.literal_eval(value)
        except (SyntaxError, ValueError):
            return value[1:-1]
    return value


def _map(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any, default: list[str]) -> list[str]:
    if value is None:
        return list(default)
    if not isinstance(value, list):
        raise ConfigValidationError("expected list config value")
    return [str(item) for item in value]


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        if value.lower() in {"true", "1", "yes", "on"}:
            return True
        if value.lower() in {"false", "0", "no", "off"}:
            return False
    return bool(value)


def _positive_int(value: Any, default: int, field: str) -> int:
    parsed = _int(value, default, field)
    if parsed <= 0:
        raise ConfigValidationError(f"{field} must be positive")
    return parsed


def _nonnegative_int(value: Any, default: int, field: str) -> int:
    parsed = _int(value, default, field)
    if parsed < 0:
        raise ConfigValidationError(f"{field} must be non-negative")
    return parsed


def _int(value: Any, default: int, field: str) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigValidationError(f"{field} must be an integer") from exc


def _state_limits(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    limits: dict[str, int] = {}
    for key, raw in value.items():
        try:
            parsed = int(raw)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            limits[str(key).lower()] = parsed
    return limits


def _resolve_env_value(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    if text.startswith("$") and len(text) > 1:
        return os.environ.get(text[1:]) or None
    return text


def _resolve_path(value: Any, base: Path) -> Path:
    text = _resolve_env_value(value) or ""
    expanded = Path(os.path.expanduser(text))
    if not expanded.is_absolute():
        expanded = base / expanded
    return expanded.resolve()


def _optional_resolved_path(value: Any, base: Path) -> Path | None:
    if value is None:
        return None
    text = _resolve_env_value(value)
    if not text:
        return None
    return _resolve_path(text, base)


def _logging_level(value: Any) -> str:
    level = str(value or "INFO").upper()
    allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    if level not in allowed:
        raise ConfigValidationError("logging.level must be one of DEBUG, INFO, WARNING, ERROR, CRITICAL")
    return level
