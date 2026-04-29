"""Runtime service entrypoint for `harness run`."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from .agent import CodexAgentRunner
from .orchestrator import Orchestrator
from .tracker import LinearClient
from .workflow import load_workflow, resolve_config, validate_dispatch_config
from .workspace import WorkspaceManager


class RuntimeServiceError(RuntimeError):
    pass


class RuntimeService:
    def __init__(self, workflow_path: Path | None = None):
        self.workflow_path = workflow_path
        self.logger = logging.getLogger("harness.runtime")

    def build_orchestrator(self) -> Orchestrator:
        workflow = load_workflow(self.workflow_path)
        config = resolve_config(workflow)
        validate_dispatch_config(config)
        tracker = LinearClient(config)
        workspace_manager = WorkspaceManager(config)
        agent_runner = CodexAgentRunner(config)
        return Orchestrator(config, tracker, workspace_manager, agent_runner, workflow.prompt_template)

    def run_forever(self) -> int:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s level=%(levelname)s %(message)s")
        try:
            orchestrator = self.build_orchestrator()
        except Exception as exc:
            raise RuntimeServiceError(f"runtime startup failed: {exc}") from exc
        orchestrator.startup_terminal_cleanup()
        self.logger.info("runtime_started workflow=%s", orchestrator.config.workflow_path)
        while True:
            orchestrator.tick_once()
            time.sleep(orchestrator.config.polling_interval_ms / 1000)
