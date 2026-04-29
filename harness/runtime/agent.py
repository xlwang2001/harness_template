"""Codex app-server runner abstraction with hardened defaults."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .models import Issue, RuntimeConfig
from .workspace import ensure_contained


class AgentRunnerError(RuntimeError):
    pass


@dataclass(frozen=True)
class AgentRunResult:
    success: bool
    session_id: str | None = None
    error: str | None = None


class CodexAgentRunner:
    """Thin, hardened launch wrapper.

    The full app-server protocol is isolated behind this class. The default
    implementation validates cwd containment and launches the configured command
    in the per-issue workspace; protocol-rich integrations can replace this
    class without changing orchestrator policy.
    """

    def __init__(self, config: RuntimeConfig):
        self.config = config

    def run_turn(self, issue: Issue, prompt: str, workspace_path: Path, attempt: int | None = None) -> AgentRunResult:
        del issue, prompt, attempt
        workspace_path = workspace_path.resolve()
        ensure_contained(self.config.workspace_root, workspace_path)
        try:
            subprocess.run(
                ["bash", "-lc", self.config.codex_command],
                cwd=workspace_path,
                timeout=self.config.codex_turn_timeout_ms / 1000,
                check=True,
                text=True,
                capture_output=True,
            )
        except FileNotFoundError as exc:
            raise AgentRunnerError("codex_not_found") from exc
        except subprocess.TimeoutExpired as exc:
            raise AgentRunnerError("turn_timeout") from exc
        except subprocess.CalledProcessError as exc:
            raise AgentRunnerError(f"turn_failed: {exc.returncode}") from exc
        return AgentRunResult(success=True)
