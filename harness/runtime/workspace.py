"""Workspace management with hardened containment checks."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from .models import RuntimeConfig, Workspace


class WorkspaceError(RuntimeError):
    pass


def sanitize_workspace_key(identifier: str) -> str:
    key = re.sub(r"[^A-Za-z0-9._-]", "_", identifier)
    return key or "issue"


class WorkspaceManager:
    def __init__(self, config: RuntimeConfig):
        self.config = config
        self.root = config.workspace_root.resolve()

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
        if created_now:
            self.run_hook("after_create", workspace, fatal=True)
        return workspace

    def run_hook(self, name: str, workspace: Workspace, *, fatal: bool) -> None:
        script = self.config.hooks.get(name)
        if not script:
            return
        try:
            subprocess.run(
                ["sh", "-lc", script],
                cwd=workspace.path,
                timeout=self.config.hooks_timeout_ms / 1000,
                check=True,
                text=True,
                capture_output=True,
            )
        except (subprocess.SubprocessError, OSError) as exc:
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


def ensure_contained(root: Path, path: Path) -> None:
    root = root.resolve()
    path = path.resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise WorkspaceError(f"workspace path escapes root: {path}") from exc
