"""Runtime service entrypoint for `harness run`."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from .agent import CodexAgentRunner
from .orchestrator import Orchestrator
from .runtime_logging import emit_runtime_log
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
        workspace_manager = WorkspaceManager(config, logger=self.logger)
        agent_runner = CodexAgentRunner(config)
        return Orchestrator(config, tracker, workspace_manager, agent_runner, workflow.prompt_template, logger=self.logger)

    def run_forever(self) -> int:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s level=%(levelname)s %(message)s")
        try:
            orchestrator = self.build_orchestrator()
        except Exception as exc:
            emit_runtime_log(self.logger, "startup_failed", level=logging.ERROR, error=exc)
            raise RuntimeServiceError(f"runtime startup failed: {exc}") from exc
        orchestrator.startup_terminal_cleanup()
        emit_runtime_log(
            self.logger,
            "runtime_started",
            workflow=orchestrator.config.workflow_path,
            workspace_root=orchestrator.config.workspace_root,
            max_concurrent_agents=orchestrator.config.max_concurrent_agents,
            secrets=(orchestrator.config.tracker_api_key,),
        )
        while True:
            reloaded = self.reloader.reload_if_changed()
            if reloaded is not None:
                workflow, config = reloaded
                orchestrator.apply_reload(config, workflow.prompt_template)
                emit_runtime_log(
                    self.logger,
                    "workflow_reloaded",
                    workflow=config.workflow_path,
                    poll_interval_ms=config.polling_interval_ms,
                    max_concurrent_agents=config.max_concurrent_agents,
                    secrets=(config.tracker_api_key,),
                )
            elif self.reloader.last_error is not None:
                emit_runtime_log(
                    self.logger,
                    "workflow_reload_failed",
                    level=logging.ERROR,
                    error=self.reloader.last_error,
                    secrets=(orchestrator.config.tracker_api_key,),
                )
            orchestrator.tick_once()
            time.sleep(orchestrator.config.polling_interval_ms / 1000)
