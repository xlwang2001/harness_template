"""Runtime service entrypoint for `harness run`."""

from __future__ import annotations

import logging
import signal
import threading
import time
from pathlib import Path
from types import FrameType

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
        self.shutdown_requested = False
        self.shutdown_reason = "shutdown"

    def build_orchestrator(self) -> Orchestrator:
        workflow, config = self.reloader.load_initial()
        tracker = LinearClient(config)
        workspace_manager = WorkspaceManager(config, logger=self.logger)
        agent_runner = CodexAgentRunner(config)
        return Orchestrator(config, tracker, workspace_manager, agent_runner, workflow.prompt_template, logger=self.logger)

    def run_forever(self) -> int:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s level=%(levelname)s %(message)s")
        previous_handlers = self._install_signal_handlers()
        orchestrator: Orchestrator | None = None
        try:
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
            while not self.shutdown_requested:
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
                if not self.shutdown_requested:
                    time.sleep(orchestrator.config.polling_interval_ms / 1000)
        except KeyboardInterrupt:
            self._request_shutdown("keyboard_interrupt")
        finally:
            self._restore_signal_handlers(previous_handlers)
        if orchestrator is not None and self.shutdown_requested:
            emit_runtime_log(
                self.logger,
                "runtime_shutdown_requested",
                reason=self.shutdown_reason,
                secrets=(orchestrator.config.tracker_api_key,),
            )
            orchestrator.shutdown(self.shutdown_reason)
            emit_runtime_log(
                self.logger,
                "runtime_shutdown_completed",
                reason=self.shutdown_reason,
                secrets=(orchestrator.config.tracker_api_key,),
            )
            return 0
        return 0

    def _install_signal_handlers(self) -> dict[int, signal.Handlers] | None:
        if threading.current_thread() is not threading.main_thread():
            return None
        previous_handlers = {}
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, self._handle_signal)
        return previous_handlers

    def _restore_signal_handlers(self, previous_handlers: dict[int, signal.Handlers] | None) -> None:
        if previous_handlers is None:
            return
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)

    def _handle_signal(self, signum: int, frame: FrameType | None) -> None:
        try:
            signal_name = signal.Signals(signum).name.lower()
        except ValueError:
            signal_name = f"signal_{signum}"
        self._request_shutdown(signal_name)

    def _request_shutdown(self, reason: str) -> None:
        if not self.shutdown_requested:
            self.shutdown_reason = reason
            self.shutdown_requested = True
