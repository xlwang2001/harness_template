"""Runtime service entrypoint for `harness run`."""

from __future__ import annotations

import logging
import signal
import threading
import time
from dataclasses import replace
from pathlib import Path
from types import FrameType

from .agent import CodexAgentRunner
from .client_tools import build_client_tools
from .orchestrator import Orchestrator
from .runtime_logging import emit_runtime_log
from .status_server import RuntimeStatusServer
from .tracker import LinearClient
from .workflow import WorkflowReloader
from .workspace import WorkspaceManager


class RuntimeServiceError(RuntimeError):
    pass


class RuntimeService:
    def __init__(self, workflow_path: Path | None = None, *, server_port_override: int | None = None):
        self.workflow_path = workflow_path
        self.server_port_override = server_port_override
        self.logger = logging.getLogger("harness.runtime")
        self.reloader = WorkflowReloader(workflow_path)
        self.shutdown_requested = False
        self.shutdown_reason = "shutdown"
        self._refresh_lock = threading.Lock()
        self._refresh_requested = False
        self._refresh_event = threading.Event()

    def build_orchestrator(self) -> Orchestrator:
        workflow, config = self.reloader.load_initial()
        config = self._apply_runtime_overrides(config)
        tracker = LinearClient(config)
        workspace_manager = WorkspaceManager(config, logger=self.logger)
        agent_runner = CodexAgentRunner(config, client_tools=build_client_tools(config))
        return Orchestrator(config, tracker, workspace_manager, agent_runner, workflow.prompt_template, logger=self.logger)

    def run_forever(self) -> int:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s level=%(levelname)s %(message)s")
        previous_handlers = self._install_signal_handlers()
        orchestrator: Orchestrator | None = None
        status_server: RuntimeStatusServer | None = None
        try:
            try:
                orchestrator = self.build_orchestrator()
            except Exception as exc:
                emit_runtime_log(self.logger, "startup_failed", level=logging.ERROR, error=exc)
                raise RuntimeServiceError(f"runtime startup failed: {exc}") from exc
            orchestrator.startup_terminal_cleanup()
            if orchestrator.config.server_enabled:
                try:
                    status_server = RuntimeStatusServer(
                        orchestrator,
                        host=orchestrator.config.server_host,
                        port=orchestrator.config.server_port,
                        request_refresh=self.request_refresh,
                    )
                    status_server.start()
                except Exception as exc:
                    if status_server is not None:
                        try:
                            status_server.stop()
                        except Exception:
                            pass
                    status_server = None
                    emit_runtime_log(
                        self.logger,
                        "status_server_failed",
                        level=logging.WARNING,
                        error=exc,
                        secrets=(orchestrator.config.tracker_api_key,),
                    )
                else:
                    emit_runtime_log(
                        self.logger,
                        "status_server_started",
                        host=status_server.server_address[0],
                        port=status_server.server_address[1],
                        secrets=(orchestrator.config.tracker_api_key,),
                    )
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
                    config = self._apply_runtime_overrides(config)
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
                    if self._wait_for_poll_or_refresh(orchestrator.config.polling_interval_ms / 1000):
                        continue
        except KeyboardInterrupt:
            self._request_shutdown("keyboard_interrupt")
        finally:
            if status_server is not None:
                status_server.stop()
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
            self._refresh_event.set()

    def request_refresh(self) -> bool:
        with self._refresh_lock:
            coalesced = self._refresh_requested
            self._refresh_requested = True
            self._refresh_event.set()
            return coalesced

    def consume_refresh_requested(self) -> bool:
        with self._refresh_lock:
            if not self._refresh_requested:
                return False
            self._refresh_requested = False
            self._refresh_event.clear()
            return True

    def _wait_for_poll_or_refresh(self, timeout: float) -> bool:
        if self._refresh_event.wait(timeout):
            return self.consume_refresh_requested()
        return False

    def _apply_runtime_overrides(self, config):
        if self.server_port_override is None:
            return config
        return replace(config, server_enabled=True, server_port=self.server_port_override)
