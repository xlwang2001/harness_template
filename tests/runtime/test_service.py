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
        tracker_handoff_state=None,
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
    def __init__(self, orchestrator, **kwargs):
        super().__init__(None, **kwargs)
        self.orchestrator = orchestrator
        self.reloader = FakeReloader()

    def build_orchestrator(self):
        if self.orchestrator is not None:
            self.orchestrator.config = self._apply_runtime_overrides(self.orchestrator.config)
        return self.orchestrator


class RuntimeServiceTests(unittest.TestCase):
    def run_service(self, service):
        original_basic_config = service_module.logging.basicConfig
        original_configure_logging = service_module.configure_runtime_logging
        service_module.logging.basicConfig = lambda *args, **kwargs: None
        service_module.configure_runtime_logging = lambda *args, **kwargs: None
        try:
            return service.run_forever()
        finally:
            service_module.logging.basicConfig = original_basic_config
            service_module.configure_runtime_logging = original_configure_logging

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

    def test_refresh_request_coalesces_until_consumed(self):
        service = RuntimeService(None)
        self.assertFalse(service.request_refresh())
        self.assertTrue(service.request_refresh())
        self.assertTrue(service.consume_refresh_requested())
        self.assertFalse(service.consume_refresh_requested())
        self.assertFalse(service.request_refresh())

    def test_run_forever_consumes_refresh_and_ticks_immediately(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            class RefreshingOrchestrator(FakeOrchestrator):
                def tick_once(self):
                    super().tick_once()
                    if self.ticks == 1:
                        service.request_refresh()
                    elif self.ticks == 2:
                        raise KeyboardInterrupt()

            service = FakeService(None)
            orchestrator = RefreshingOrchestrator(config(root))
            service.orchestrator = orchestrator
            code = self.run_service(service)
            self.assertEqual(code, 0)
            self.assertEqual(orchestrator.ticks, 2)

    def test_run_forever_starts_and_stops_enabled_status_server(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cfg = RuntimeConfig(**{**config(root).__dict__, "server_enabled": True, "server_port": 0})
            calls = []

            class ServerOrchestrator(FakeOrchestrator):
                def tick_once(self):
                    super().tick_once()
                    raise KeyboardInterrupt()

            class FakeStatusServer:
                def __init__(self, orchestrator, *, host, port, request_refresh):
                    calls.append(("init", host, port))
                    self.server_address = (host, 12345)

                def start(self):
                    calls.append(("start",))

                def stop(self):
                    calls.append(("stop",))

            original_server = service_module.RuntimeStatusServer
            try:
                service_module.RuntimeStatusServer = FakeStatusServer
                service = FakeService(ServerOrchestrator(cfg))
                code = self.run_service(service)
            finally:
                service_module.RuntimeStatusServer = original_server
            self.assertEqual(code, 0)
            self.assertEqual(calls, [("init", "127.0.0.1", 0), ("start",), ("stop",)])

    def test_port_override_enables_status_server(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cfg = RuntimeConfig(**{**config(root).__dict__, "server_enabled": False, "server_port": 8765})
            calls = []

            class ServerOrchestrator(FakeOrchestrator):
                def tick_once(self):
                    super().tick_once()
                    raise KeyboardInterrupt()

            class FakeStatusServer:
                def __init__(self, orchestrator, *, host, port, request_refresh):
                    calls.append(("init", host, port))
                    self.server_address = (host, port)

                def start(self):
                    calls.append(("start",))

                def stop(self):
                    calls.append(("stop",))

            original_server = service_module.RuntimeStatusServer
            try:
                service_module.RuntimeStatusServer = FakeStatusServer
                service = FakeService(ServerOrchestrator(cfg), server_port_override=0)
                code = self.run_service(service)
            finally:
                service_module.RuntimeStatusServer = original_server
            self.assertEqual(code, 0)
            self.assertEqual(calls, [("init", "127.0.0.1", 0), ("start",), ("stop",)])

    def test_reload_applies_port_override_without_rebinding(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            initial = RuntimeConfig(**{**config(root).__dict__, "server_enabled": False, "server_port": 8765})
            reloaded = RuntimeConfig(**{**config(root).__dict__, "server_enabled": False, "server_port": 9999})

            class OneReload:
                last_error = None

                def __init__(self):
                    self.used = False

                def reload_if_changed(self):
                    if self.used:
                        return None
                    self.used = True
                    return type("Workflow", (), {"prompt_template": "Work"})(), reloaded

            class ReloadOrchestrator(FakeOrchestrator):
                def apply_reload(self, cfg, prompt_template):
                    self.config = cfg

                def tick_once(self):
                    super().tick_once()
                    raise KeyboardInterrupt()

            orchestrator = ReloadOrchestrator(initial)
            service = FakeService(orchestrator, server_port_override=0)
            service.reloader = OneReload()
            code = self.run_service(service)
            self.assertEqual(code, 0)
            self.assertTrue(orchestrator.config.server_enabled)
            self.assertEqual(orchestrator.config.server_port, 0)

    def test_reload_reconfigures_runtime_logging(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first_log = root / "first.log"
            second_log = root / "second.log"
            initial = RuntimeConfig(**{**config(root).__dict__, "logging_file": first_log})
            reloaded = RuntimeConfig(**{**config(root).__dict__, "logging_level": "DEBUG", "logging_console": False, "logging_file": second_log})
            calls = []

            class OneReload:
                last_error = None

                def __init__(self):
                    self.used = False

                def reload_if_changed(self):
                    if self.used:
                        return None
                    self.used = True
                    return type("Workflow", (), {"prompt_template": "Work"})(), reloaded

            class ReloadOrchestrator(FakeOrchestrator):
                def apply_reload(self, cfg, prompt_template):
                    self.config = cfg

                def tick_once(self):
                    super().tick_once()
                    raise KeyboardInterrupt()

            original_configure_logging = service_module.configure_runtime_logging
            try:
                service_module.configure_runtime_logging = lambda logger, **kwargs: calls.append(kwargs)
                orchestrator = ReloadOrchestrator(initial)
                service = FakeService(orchestrator)
                service.reloader = OneReload()
                code = service.run_forever()
            finally:
                service_module.configure_runtime_logging = original_configure_logging

            self.assertEqual(code, 0)
            self.assertEqual(calls[0]["level"], "INFO")
            self.assertIsNone(calls[0]["file_path"])
            self.assertEqual(calls[1]["file_path"], first_log)
            self.assertEqual(calls[2]["level"], "DEBUG")
            self.assertFalse(calls[2]["console"])
            self.assertEqual(calls[2]["file_path"], second_log)

    def test_status_server_start_failure_does_not_crash_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cfg = RuntimeConfig(**{**config(root).__dict__, "server_enabled": True, "server_port": 0})
            calls = []

            class ServerOrchestrator(FakeOrchestrator):
                def tick_once(self):
                    super().tick_once()
                    raise KeyboardInterrupt()

            class FailingStatusServer:
                def __init__(self, orchestrator, *, host, port, request_refresh):
                    calls.append(("init", host, port))

                def start(self):
                    calls.append(("start",))
                    raise OSError("port unavailable")

            original_server = service_module.RuntimeStatusServer
            try:
                service_module.RuntimeStatusServer = FailingStatusServer
                service = FakeService(ServerOrchestrator(cfg))
                code = self.run_service(service)
            finally:
                service_module.RuntimeStatusServer = original_server
            self.assertEqual(code, 0)
            self.assertEqual(calls, [("init", "127.0.0.1", 0), ("start",)])
