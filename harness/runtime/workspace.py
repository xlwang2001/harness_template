"""Workspace management with hardened containment checks."""

from __future__ import annotations

import re
import shutil
import subprocess
import logging
from pathlib import Path

from .models import RuntimeConfig, Workspace
from .runtime_logging import emit_runtime_log


class WorkspaceError(RuntimeError):
    pass


def sanitize_workspace_key(identifier: str) -> str:
    key = re.sub(r"[^A-Za-z0-9._-]", "_", identifier)
    return key or "issue"


class WorkspaceManager:
    def __init__(self, config: RuntimeConfig, logger: logging.Logger | None = None):
        self.config = config
        self.root = config.workspace_root.resolve()
        self.logger = logger or logging.getLogger("harness.runtime")

    def path_for_issue(self, identifier: str) -> Path:
        path = (self.root / sanitize_workspace_key(identifier)).resolve()
        ensure_contained(self.root, path)
        return path

    def create_for_issue(self, identifier: str) -> Workspace:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.path_for_issue(identifier)
        if path.exists() and not path.is_dir():
            raise WorkspaceError(f"workspace path exists and is not a directory: {path}")
        created_now = not path.exists()
        path.mkdir(parents=True, exist_ok=True)
        workspace = Workspace(path=path, workspace_key=path.name, created_now=created_now)
        emit_runtime_log(
            self.logger,
            "workspace_prepared",
            workspace=workspace.path,
            workspace_key=workspace.workspace_key,
            created_now=workspace.created_now,
            secrets=(self.config.tracker_api_key,),
        )
        if created_now:
            self.run_hook("after_create", workspace, fatal=True)
        return workspace

    def run_hook(self, name: str, workspace: Workspace, *, fatal: bool) -> None:
        script = self.config.hooks.get(name)
        if not script:
            return
        emit_runtime_log(
            self.logger,
            "hook_started",
            hook=name,
            workspace=workspace.path,
            secrets=(self.config.tracker_api_key,),
        )
        try:
            subprocess.run(
                ["sh", "-lc", script],
                cwd=workspace.path,
                timeout=self.config.hooks_timeout_ms / 1000,
                check=True,
                text=True,
                capture_output=True,
            )
            emit_runtime_log(
                self.logger,
                "hook_completed",
                hook=name,
                workspace=workspace.path,
                secrets=(self.config.tracker_api_key,),
            )
        except (subprocess.SubprocessError, OSError) as exc:
            emit_runtime_log(
                self.logger,
                "hook_failed",
                level=logging.ERROR if fatal else logging.WARNING,
                hook=name,
                workspace=workspace.path,
                fatal=fatal,
                error=exc,
                secrets=(self.config.tracker_api_key,),
            )
            if fatal:
                raise WorkspaceError(f"{name} hook failed: {exc}") from exc

    def cleanup_for_issue(self, identifier: str) -> None:
        path = self.path_for_issue(identifier)
        if not path.exists():
            return
        workspace = Workspace(path=path, workspace_key=path.name, created_now=False)
        self.run_hook("before_remove", workspace, fatal=False)
        ensure_contained(self.root, path)
        shutil.rmtree(path)
        emit_runtime_log(
            self.logger,
            "workspace_removed",
            workspace=path,
            workspace_key=workspace.workspace_key,
            secrets=(self.config.tracker_api_key,),
        )


def ensure_contained(root: Path, path: Path) -> None:
    root = root.resolve()
    path = path.resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise WorkspaceError(f"workspace path escapes root: {path}") from exc
