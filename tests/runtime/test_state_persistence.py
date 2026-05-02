import json
import logging
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from harness.runtime.models import RetryEntry, RunAttemptRecord, RuntimeState
from harness.runtime.state_persistence import RuntimeStateStore


class RuntimeStatePersistenceTests(unittest.TestCase):
    def test_round_trips_safe_scheduler_state(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state" / "runtime.json"
            state = RuntimeState(poll_interval_ms=30000, max_concurrent_agents=2)
            state.retry_attempts["abc-1"] = RetryEntry(
                issue_id="abc-1",
                identifier="ABC-1",
                attempt=3,
                due_at_ms=123456,
                error="agent failed",
            )
            started = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
            finished = datetime(2026, 1, 1, 12, 1, tzinfo=timezone.utc)
            state.last_attempts["abc-1"] = RunAttemptRecord(
                issue_id="abc-1",
                identifier="ABC-1",
                attempt=2,
                workspace_path=Path(directory) / "ABC-1",
                started_at=started,
                finished_at=finished,
                status="failed",
                error="agent failed",
            )
            state.completed.add("abc-2")
            state.codex_totals = {
                "input_tokens": 10,
                "output_tokens": 5,
                "total_tokens": 15,
                "seconds_running": 7.5,
            }
            state.codex_rate_limits = {"primary": {"remaining": 8}}
            state.session_metadata["abc-1"] = {
                "issue_identifier": "ABC-1",
                "session_id": "session-1",
                "thread_id": "thread-1",
                "turn_id": "turn-2",
                "turn_count": 2,
                "last_codex_event": "turn_completed",
                "last_codex_timestamp": finished.isoformat(),
                "last_codex_message": "done",
                "codex_input_tokens": 10,
                "codex_output_tokens": 5,
                "codex_total_tokens": 15,
                "codex_app_server_pid": "12345",
                "tracker_api_key": "secret-token",
            }

            RuntimeStateStore(path).save(state, persist_retries=True, persist_sessions=True)

            raw = path.read_text(encoding="utf-8")
            self.assertNotIn("secret-token", raw)
            self.assertNotIn("codex_app_server_pid", raw)
            loaded_payload = json.loads(raw)
            self.assertEqual(loaded_payload["version"], 1)

            restored = RuntimeState(poll_interval_ms=30000, max_concurrent_agents=2)
            RuntimeStateStore(path).load_into(restored, persist_retries=True, persist_sessions=True)

            self.assertEqual(restored.retry_attempts["abc-1"].attempt, 3)
            self.assertEqual(restored.last_attempts["abc-1"].status, "failed")
            self.assertEqual(restored.last_attempts["abc-1"].workspace_path, Path(directory) / "ABC-1")
            self.assertEqual(restored.completed, {"abc-2"})
            self.assertEqual(restored.codex_totals["input_tokens"], 10)
            self.assertEqual(restored.codex_totals["seconds_running"], 7.5)
            self.assertEqual(restored.codex_rate_limits, {"primary": {"remaining": 8}})
            self.assertEqual(restored.session_metadata["abc-1"]["session_id"], "session-1")
            self.assertNotIn("codex_app_server_pid", restored.session_metadata["abc-1"])

    def test_can_disable_retry_and_session_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runtime.json"
            state = RuntimeState(poll_interval_ms=30000, max_concurrent_agents=2)
            state.retry_attempts["abc-1"] = RetryEntry("abc-1", "ABC-1", 1, 0, None)
            state.session_metadata["abc-1"] = {"session_id": "session-1"}
            RuntimeStateStore(path).save(state, persist_retries=False, persist_sessions=False)

            restored = RuntimeState(poll_interval_ms=30000, max_concurrent_agents=2)
            RuntimeStateStore(path).load_into(restored, persist_retries=True, persist_sessions=True)

            self.assertEqual(restored.retry_attempts, {})
            self.assertEqual(restored.session_metadata, {})

    def test_corrupt_state_logs_warning_and_starts_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runtime.json"
            path.write_text("{", encoding="utf-8")
            logger = logging.getLogger("harness.runtime.test.state_load")
            state = RuntimeState(poll_interval_ms=30000, max_concurrent_agents=2)

            with self.assertLogs(logger, level="WARNING") as captured:
                RuntimeStateStore(path, logger).load_into(state, persist_retries=True, persist_sessions=True)

            self.assertIn("event=runtime_state_load_failed", "\n".join(captured.output))
            self.assertEqual(state.retry_attempts, {})
            self.assertEqual(state.session_metadata, {})

    def test_save_failure_logs_warning_and_continues(self):
        with tempfile.TemporaryDirectory() as directory:
            blocked = Path(directory) / "not-a-directory"
            blocked.write_text("blocked", encoding="utf-8")
            path = blocked / "runtime.json"
            logger = logging.getLogger("harness.runtime.test.state_save")
            state = RuntimeState(poll_interval_ms=30000, max_concurrent_agents=2)

            with self.assertLogs(logger, level="WARNING") as captured:
                RuntimeStateStore(path, logger).save(state, persist_retries=True, persist_sessions=True)

            self.assertIn("event=runtime_state_save_failed", "\n".join(captured.output))


if __name__ == "__main__":
    unittest.main()
