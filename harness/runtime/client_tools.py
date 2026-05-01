"""Runtime-owned client-side tools for Codex app-server sessions."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping

from .models import RuntimeConfig


@dataclass(frozen=True)
class ClientToolResult:
    success: bool
    output: Any


def build_client_tools(config: RuntimeConfig) -> dict[str, object]:
    if config.tracker_kind != "linear":
        return {}
    return {"linear_graphql": LinearGraphQLTool(config)}


class LinearGraphQLTool:
    def __init__(self, config: RuntimeConfig):
        self.config = config

    def __call__(self, arguments: Any) -> ClientToolResult:
        parsed = _parse_linear_graphql_arguments(arguments)
        if not parsed.success:
            return parsed
        query = parsed.output["query"]
        variables = parsed.output["variables"]
        if self.config.tracker_kind != "linear":
            return _failure("unsupported_tracker_kind")
        if not self.config.tracker_api_key:
            return _failure("missing_auth")
        request = urllib.request.Request(
            self.config.tracker_endpoint,
            data=json.dumps({"query": query, "variables": variables}).encode("utf-8"),
            headers={
                "Authorization": self.config.tracker_api_key,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                if response.status != 200:
                    return _failure("linear_api_status", status=response.status)
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return _failure("linear_api_status", status=exc.code)
        except urllib.error.URLError as exc:
            return _failure("linear_api_request", reason=str(exc.reason))
        except json.JSONDecodeError:
            return _failure("linear_unknown_payload")
        if not isinstance(payload, dict):
            return _failure("linear_unknown_payload")
        if payload.get("errors"):
            return ClientToolResult(success=False, output={"error": "linear_graphql_errors", "response": payload})
        return ClientToolResult(success=True, output=payload)


def _parse_linear_graphql_arguments(arguments: Any) -> ClientToolResult:
    if isinstance(arguments, str):
        query = arguments
        variables: dict[str, Any] = {}
    elif isinstance(arguments, Mapping):
        if "operationName" in arguments or "operation_name" in arguments:
            return _failure("operation_name_not_supported")
        query = arguments.get("query")
        variables = arguments.get("variables", {})
        if not isinstance(query, str):
            return _failure("invalid_query")
        if not isinstance(variables, Mapping):
            return _failure("invalid_variables")
        variables = dict(variables)
    else:
        return _failure("invalid_input")
    if not query.strip():
        return _failure("empty_query")
    if not _has_single_graphql_operation(query):
        return _failure("invalid_operation_count")
    if _graphql_operation_kind(query) == "subscription":
        return _failure("unsupported_operation")
    return ClientToolResult(success=True, output={"query": query, "variables": variables})


def _has_single_graphql_operation(query: str) -> bool:
    stripped = query.strip()
    sanitized = _strip_graphql_comments_and_strings(query)
    operations = re.findall(r"\b(query|mutation|subscription)\b", sanitized)
    if stripped.startswith("{"):
        return len(operations) == 0
    return len(operations) == 1


def _graphql_operation_kind(query: str) -> str | None:
    sanitized = _strip_graphql_comments_and_strings(query)
    match = re.search(r"\b(query|mutation|subscription)\b", sanitized)
    return match.group(1) if match else "query"


def _strip_graphql_comments_and_strings(query: str) -> str:
    output: list[str] = []
    index = 0
    while index < len(query):
        char = query[index]
        if char == "#":
            while index < len(query) and query[index] != "\n":
                output.append(" ")
                index += 1
            continue
        if query.startswith('"""', index):
            output.extend("   ")
            index += 3
            while index < len(query) and not query.startswith('"""', index):
                output.append("\n" if query[index] == "\n" else " ")
                index += 1
            if query.startswith('"""', index):
                output.extend("   ")
                index += 3
            continue
        if char == '"':
            output.append(" ")
            index += 1
            escaped = False
            while index < len(query):
                current = query[index]
                output.append("\n" if current == "\n" else " ")
                index += 1
                if escaped:
                    escaped = False
                elif current == "\\":
                    escaped = True
                elif current == '"':
                    break
            continue
        output.append(char)
        index += 1
    return "".join(output)


def _failure(error: str, **extra: Any) -> ClientToolResult:
    payload = {"error": error}
    payload.update(extra)
    return ClientToolResult(success=False, output=payload)
