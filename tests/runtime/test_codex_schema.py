import json
import os
import shutil
import shlex
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from harness.runtime.agent import CodexAgentRunner
from harness.runtime.client_tools import ClientToolResult

from tests.runtime.test_agent import FAKE_SERVER, config, issue


def _schema_dir(testcase: unittest.TestCase) -> Path:
    configured = os.environ.get("HARNESS_CODEX_SCHEMA_DIR")
    if configured:
        path = Path(configured)
        if not path.is_dir():
            testcase.skipTest(f"HARNESS_CODEX_SCHEMA_DIR is not a directory: {path}")
        return path
    if os.environ.get("HARNESS_CODEX_GENERATE_SCHEMA") != "1":
        testcase.skipTest("set HARNESS_CODEX_SCHEMA_DIR or HARNESS_CODEX_GENERATE_SCHEMA=1")
    codex = shutil.which("codex")
    if codex is None:
        testcase.skipTest("codex executable not found")
    path = Path(tempfile.mkdtemp(prefix="harness-codex-schema-"))
    testcase.addCleanup(shutil.rmtree, path, ignore_errors=True)
    try:
        subprocess.run([codex, "app-server", "generate-json-schema", "--out", str(path)], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        testcase.skipTest(f"could not generate Codex schema: {exc}")
    return path


def _load_validator(testcase: unittest.TestCase, schema_path: Path):
    try:
        import jsonschema
    except ImportError:
        testcase.skipTest("install the 'schema' extra to run Codex schema validation")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    return jsonschema.Draft7Validator(schema)


def _assert_valid(testcase: unittest.TestCase, validator, payload: object) -> None:
    errors = sorted(validator.iter_errors(payload), key=lambda error: list(error.path))
    if errors:
        testcase.fail("; ".join(error.message for error in errors[:5]))


class CodexSchemaTests(unittest.TestCase):
    def test_runner_envelopes_match_generated_schema(self):
        schema_dir = _schema_dir(self)
        client_request = _load_validator(self, schema_dir / "ClientRequest.json")
        jsonrpc_response = _load_validator(self, schema_dir / "JSONRPCResponse.json")
        command_approval_response = _load_validator(self, schema_dir / "CommandExecutionRequestApprovalResponse.json")
        permissions_approval_response = _load_validator(self, schema_dir / "PermissionsRequestApprovalResponse.json")
        dynamic_tool_response = _load_validator(self, schema_dir / "DynamicToolCallResponse.json")

        records = self._run_fake_server("approval_tools", client_tools={"echo": lambda arguments: {"echoed": arguments}})
        records.extend(
            self._run_fake_server(
                "linear_graphql",
                client_tools={"linear_graphql": lambda arguments: ClientToolResult(True, {"data": {"ok": True}, "arguments": arguments})},
            )
        )

        for message in records:
            if "method" in message:
                self.assertNotEqual(message["method"], "shutdown")
                _assert_valid(self, client_request, message)
                continue
            _assert_valid(self, jsonrpc_response, message)
            if message.get("id") == "approval-1":
                _assert_valid(self, command_approval_response, message["result"])
            if message.get("id") == "permissions-1":
                _assert_valid(self, permissions_approval_response, message["result"])
            if message.get("id") in {"tool-unsupported", "tool-supported", "linear-1"}:
                _assert_valid(self, dynamic_tool_response, message["result"])

    def _run_fake_server(self, mode: str, *, client_tools: dict):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            server = root / "fake_codex_server.py"
            record = root / "record.json"
            server.write_text(textwrap.dedent(FAKE_SERVER), encoding="utf-8")
            workspace = root / "workspace"
            workspace.mkdir()
            command = " ".join(
                [
                    f"FAKE_CODEX_MODE={shlex.quote(mode)}",
                    f"FAKE_CODEX_RECORD={shlex.quote(str(record))}",
                    shlex.quote(sys.executable),
                    shlex.quote(str(server)),
                ]
            )
            runner = CodexAgentRunner(config(root, command=command), client_tools=client_tools)
            runner.run_turn(issue(), "Do the work", workspace)
            return json.loads(record.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
