import signal
import tempfile
import unittest
from pathlib import Path

import harness.runtime.service as service_module
from harness.runtime.models import RuntimeConfig
from harness.runtime.service import RuntimeService


def config(root: Path) -> RuntimeConfig:
    return RuntimeConfig(
        workflow_path=root / "WORKFLOW.md",
        tracker_kind="linear",
        tracker_endpoint="https://api.linear.app/graphql",
        tracker_api_key="token",
        tracker_project_slug="project",
        active_states=("Todo", "In Progress"),
        terminal_states=("Done", "Cancelled"),
        polling_interval_ms=1,
        workspace_root=root,
        hooks={"after_create": None, "before_run": None, "after_run": None, "before_remove": None},
        hooks_timeout_ms=1000,
        max_concurrent_agents=1,
        max_turns=20,
        max_retry_backoff_ms=300000,
        max_concurrent_agents_by_state={},
        codex_command="true",
        codex_turn_timeout_ms=1000,
        codex_read_timeout_ms=1000,
        codex_stall_timeout_ms=300000,
        approval_policy="on-request",
        thread_sandbox="workspace-write",
        turn_sandbox_policy="workspace-write",
    )


class FakeReloader:
    last_error = None

    def reload_if_changed(self):
        return None


class FakeOrchestrator:
    def __init__(self, cfg, *, interrupt=False, signal_handlers=None):
        self.config = cfg
        self.interrupt = interrupt
        self.signal_handlers = signal_handlers
        self.startup_cleanups = 0
        self.ticks = 0
        self.shutdown_calls = []

    def startup_terminal_cleanup(self):
        self.startup_cleanups += 1

    def tick_once(self):
        self.ticks += 1
        if self.interrupt:
            raise KeyboardInterrupt()
        if self.signal_handlers:
            self.signal_handlers[signal.SIGTERM](signal.SIGTERM, None)

    def shutdown(self, reason):
        self.shutdown_calls.append(reason)


class FakeService(RuntimeService):
    def __init__(self, orchestrator):
        super().__init__(None)
        self.orchestrator = orchestrator
        self.reloader = FakeReloader()

    def build_orchestrator(self):
        return self.orchestrator


class RuntimeServiceTests(unittest.TestCase):
    def run_service(self, service):
        original_basic_config = service_module.logging.basicConfig
        service_module.logging.basicConfig = lambda *args, **kwargs: None
        try:
            return service.run_forever()
        finally:
            service_module.logging.basicConfig = original_basic_config

    def test_run_forever_returns_zero_and_shutdown_once_on_keyboard_interrupt(self):
        with tempfile.TemporaryDirectory() as directory:
            orchestrator = FakeOrchestrator(config(Path(directory)), interrupt=True)
            service = FakeService(orchestrator)
            code = self.run_service(service)
            self.assertEqual(code, 0)
            self.assertEqual(orchestrator.shutdown_calls, ["keyboard_interrupt"])
            self.assertEqual(orchestrator.ticks, 1)

    def test_signal_shutdown_exits_after_current_tick_and_restores_handlers(self):
        with tempfile.TemporaryDirectory() as directory:
            installed = {}
            calls = []
            old_handlers = {
                signal.SIGINT: service_module.signal.getsignal(signal.SIGINT),
                signal.SIGTERM: service_module.signal.getsignal(signal.SIGTERM),
            }
            original_signal = service_module.signal.signal
            original_sleep = service_module.time.sleep

            def fake_signal(signum, handler):
                calls.append((signum, handler))
                installed[signum] = handler

            def fail_sleep(seconds):
                raise AssertionError("sleep should not run after signal shutdown")

            try:
                service_module.signal.signal = fake_signal
                service_module.time.sleep = fail_sleep
                orchestrator = FakeOrchestrator(config(Path(directory)), signal_handlers=installed)
                service = FakeService(orchestrator)
                code = self.run_service(service)
            finally:
                service_module.signal.signal = original_signal
                service_module.time.sleep = original_sleep

            self.assertEqual(code, 0)
            self.assertEqual(orchestrator.ticks, 1)
            self.assertEqual(orchestrator.shutdown_calls, ["sigterm"])
            self.assertEqual(
                calls[:2],
                [(signal.SIGINT, service._handle_signal), (signal.SIGTERM, service._handle_signal)],
            )
            self.assertEqual(
                calls[-2:],
                [(signal.SIGINT, old_handlers[signal.SIGINT]), (signal.SIGTERM, old_handlers[signal.SIGTERM])],
            )
