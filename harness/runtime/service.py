"""Runtime service entrypoint for `harness run`."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from .agent import CodexAgentRunner
from .orchestrator import Orchestrator
from .tracker import LinearClient
from .workflow import WorkflowReloader
from .workspace import WorkspaceManager


class RuntimeServiceError(RuntimeError):
    pass


class RuntimeService:
    def __init__(self, workflow_path: Path | None = None):
        self.workflow_path = workflow_path
        self.logger = logging.getLogger("harness.runtime")
        self.reloader = WorkflowReloader(workflow_path)

    def build_orchestrator(self) -> Orchestrator:
        workflow, config = self.reloader.load_initial()
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
            reloaded = self.reloader.reload_if_changed()
            if reloaded is not None:
                workflow, config = reloaded
                orchestrator.apply_reload(config, workflow.prompt_template)
                self.logger.info("workflow_reloaded workflow=%s", config.workflow_path)
            elif self.reloader.last_error is not None:
                self.logger.error("workflow_reload_failed error=%s", self.reloader.last_error)
            orchestrator.tick_once()
            time.sleep(orchestrator.config.polling_interval_ms / 1000)
