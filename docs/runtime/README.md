# Hardened Runtime

This runtime follows the upstream [Symphony service specification](https://github.com/openai/symphony/blob/main/SPEC.md) while keeping implementation and safety policy in this repository.

## Core Components

- Workflow loader and config resolver
- Linear-compatible issue tracker adapter
- Workspace manager with path containment checks
- Orchestrator with polling, reconciliation, retries, and bounded concurrency
- Codex app-server runner with a stdio JSON-lines protocol adapter
- Structured runtime snapshot state

## Current Limitations

The runtime has a hardened orchestration boundary and conformance tests, and `CodexAgentRunner` now owns app-server launch, schema-aligned session/thread/turn startup, event streaming, timeout handling, and terminal error mapping. `SPEC.md` intentionally defers exact protocol envelopes to the targeted Codex app-server version, so run `make codex-schema-test` after installing the optional `schema` test extra when upgrading Codex.

User-input-required events fail the current run immediately as `turn_input_required`; the orchestrator then applies the normal retry policy. Command and file-change approval requests are auto-approved according to the documented high-trust runtime posture. Registered client-side tools are handled by explicit runtime handlers, while unsupported tool calls return structured failures and allow the session to continue. These policies keep runs from waiting indefinitely for operator input or unsupported tool execution.

When the runtime uses the Linear tracker, it can answer the optional `linear_graphql` client-side tool request. The tool reuses configured Linear credentials, accepts one GraphQL operation per call, and returns structured success or failure payloads that the agent can inspect without reading raw tokens. Tool startup advertisement is intentionally limited to fields supported by the targeted generated Codex schema.

The optional status API is disabled by default. Enable it with `server.port` in `WORKFLOW.md` or with `harness run --port PORT`; the CLI port overrides workflow config. `server.enabled: true` remains accepted as a compatibility shorthand and uses port `8765` when no port is given. The server binds to `server.host` (default `127.0.0.1`) and serves `/`, `GET /api/v1/state`, `GET /api/v1/<issue_identifier>`, and `POST /api/v1/refresh`. Listener changes require a runtime restart.

Runtime logs are structured `key=value` records from the `harness.runtime` logger. Configure sinks in `WORKFLOW.md` with `logging.level` (`DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL`), `logging.console` (default `true`), and optional `logging.file`. Relative log file paths resolve from the workflow directory. Valid workflow reloads reconfigure harness-owned log handlers without removing external handlers; file sink failures are logged as `log_sink_failed` warnings and do not stop orchestration.

## Real Integration Profile

The real integration profile is opt-in production-readiness smoke coverage. Normal CI and `make test` discover the tests but skip them unless `HARNESS_RUN_INTEGRATION=1` is set.

Run it with:

```sh
HARNESS_RUN_INTEGRATION=1 \
LINEAR_API_KEY=... \
LINEAR_PROJECT_SLUG=... \
make integration-test
```

The profile includes an in-process service-loop smoke that uses runtime fakes for the tracker and runner so it can exercise startup cleanup, one dispatch tick, preserved workspace reuse, shutdown, and restart-empty-state behavior without touching external services. This protects the production-facing orchestration path while keeping the external integration gates explicit.

The Linear smoke tests build a temporary `WORKFLOW.md`, resolve the same runtime config path as production, validate dispatch config, and perform read-only candidate and terminal-state fetches for the configured project. They do not require issues to exist and do not mutate Linear state.

Set `HARNESS_INTEGRATION_CODEX_COMMAND` to run the Codex app-server smoke against a real command, for example `codex app-server`. That check creates an isolated temporary workspace and runs one minimal turn through `CodexAgentRunner`; protocol, launch, or authentication failures fail only this explicitly enabled profile. `HARNESS_INTEGRATION_WORKSPACE_ROOT` can point the temporary workspaces at a specific local root; otherwise the system temp directory is used. Temporary workspaces are removed by the test harness when the process exits normally.

## Operator Runbooks

Runtime operator procedures live in `docs/runtime/runbooks.md`. They cover workspace cleanup, logs, failure modes, dashboard/API operation, and SPEC compatibility upgrades.

Use `docs/runtime/production-readiness-checklist.md` before first production use and whenever Codex app-server, Linear configuration, workflow dispatch policy, or runtime templates change.

## Workflow Front Matter Subset

The standard-library parser intentionally supports a documented YAML subset: nested maps by indentation, lists with `- ` items, quoted or unquoted scalars, integers, booleans, null values, comments, blank lines, and `|` block scalars. Unsupported YAML features should fail parsing instead of being guessed. This subset covers scaffold `WORKFLOW.md` templates while keeping dependency policy explicit.

## Reference Material

The upstream Symphony repository remains useful for its service specification and `.codex/skills`. Its implementation code is not used as this runtime's execution path.
