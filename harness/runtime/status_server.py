"""Optional loopback HTTP status API for the runtime."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable
from urllib.parse import unquote, urlparse

from .orchestrator import Orchestrator


RefreshCallback = Callable[[], bool]


class RuntimeStatusServer:
    def __init__(self, orchestrator: Orchestrator, *, host: str, port: int, request_refresh: RefreshCallback):
        self.orchestrator = orchestrator
        self.request_refresh = request_refresh
        self.httpd = _RuntimeHTTPServer((host, port), _StatusHandler, orchestrator, request_refresh)
        self.thread: threading.Thread | None = None

    @property
    def server_address(self) -> tuple[str, int]:
        host, port = self.httpd.server_address
        return str(host), int(port)

    def start(self) -> None:
        self.thread = threading.Thread(target=self.httpd.serve_forever, name="runtime-status-http", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        if self.thread is not None:
            self.thread.join(timeout=2)


class _RuntimeHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address, handler_class, orchestrator: Orchestrator, request_refresh: RefreshCallback):
        super().__init__(server_address, handler_class)
        self.orchestrator = orchestrator
        self.request_refresh = request_refresh


class _StatusHandler(BaseHTTPRequestHandler):
    server: _RuntimeHTTPServer

    def do_GET(self) -> None:
        self._write_response(handle_status_request("GET", self.path, self.server.orchestrator, self.server.request_refresh))

    def do_POST(self) -> None:
        self._write_response(handle_status_request("POST", self.path, self.server.orchestrator, self.server.request_refresh))

    def do_PUT(self) -> None:
        self._method_not_allowed_or_not_found()

    def do_DELETE(self) -> None:
        self._method_not_allowed_or_not_found()

    def do_PATCH(self) -> None:
        self._method_not_allowed_or_not_found()

    def _method_not_allowed_or_not_found(self) -> None:
        self._write_response(handle_status_request(self.command, self.path, self.server.orchestrator, self.server.request_refresh))

    def _write_response(self, response: tuple[int, str, bytes]) -> None:
        status, content_type, body = response
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:
        return


def handle_status_request(
    method: str,
    raw_path: str,
    orchestrator: Orchestrator,
    request_refresh: RefreshCallback,
) -> tuple[int, str, bytes]:
    path = urlparse(raw_path).path
    if method == "GET":
        if path == "/":
            return _html(200, "<!doctype html><title>Runtime Status</title><h1>Runtime Status</h1><p>See <a href=\"/api/v1/state\">/api/v1/state</a>.</p>")
        if path == "/api/v1/state":
            return _json(200, orchestrator.snapshot())
        if path == "/api/v1/refresh":
            return _error(405, "method_not_allowed", "method not allowed")
        prefix = "/api/v1/"
        if path.startswith(prefix) and len(path) > len(prefix):
            identifier = unquote(path[len(prefix) :])
            detail = orchestrator.issue_detail(identifier)
            if detail is None:
                return _error(404, "issue_not_found", f"issue not found: {identifier}")
            return _json(200, detail)
        return _error(404, "not_found", f"path not found: {path}")
    if method == "POST":
        if path == "/api/v1/refresh":
            coalesced = request_refresh()
            return _json(
                202,
                {
                    "queued": True,
                    "coalesced": coalesced,
                    "requested_at": datetime.now(timezone.utc).isoformat(),
                    "operations": ["poll", "reconcile"],
                },
            )
        if path in {"/", "/api/v1/state"} or path.startswith("/api/v1/"):
            return _error(405, "method_not_allowed", "method not allowed")
        return _error(404, "not_found", f"path not found: {path}")
    if path == "/" or path == "/api/v1/state" or path == "/api/v1/refresh" or path.startswith("/api/v1/"):
        return _error(405, "method_not_allowed", "method not allowed")
    return _error(404, "not_found", f"path not found: {path}")


def _json(status: int, payload: object) -> tuple[int, str, bytes]:
    return status, "application/json", json.dumps(payload, sort_keys=True).encode("utf-8")


def _html(status: int, body_text: str) -> tuple[int, str, bytes]:
    return status, "text/html; charset=utf-8", body_text.encode("utf-8")


def _error(status: int, code: str, message: str) -> tuple[int, str, bytes]:
    return _json(status, {"error": {"code": code, "message": message}})
