# Runtime Runbooks

These runbooks are local operator procedures for the hardened runtime. They assume a trusted local deployment with Linear credentials supplied through `WORKFLOW.md` environment indirection and Codex auth already available on the host.

## Workspace Cleanup

Use this when disk usage grows, a workspace contains stale local state, or a terminal issue did not clean up as expected.

1. Check the configured `workspace.root` in `WORKFLOW.md`.
2. Confirm the issue is terminal in the tracker before deleting its workspace manually.
3. Prefer tracker-driven cleanup first: move the issue to a configured terminal state and let the next reconciliation or restart cleanup remove the workspace.
4. If manual cleanup is required, remove only the sanitized issue directory under `workspace.root`; never delete the workspace root itself while the runtime is active.
5. Run `python3 -m harness.cli validate --target templates/repo` after changing templates or docs that describe workspace policy.

If cleanup fails, inspect hook configuration. `before_remove` failures are logged and ignored by the runtime, but shell permission errors can still leave files behind for an operator to remove.

## Logs And Observability

Use this when startup, dispatch, retry, hook, or Codex behavior is unclear.

1. Start with structured log events from the `harness.runtime` logger.
2. Look for `startup_failed`, `workflow_reload_failed`, `dispatch_preflight_failed`, `candidate_fetch_failed`, `agent_session_failed`, `retry_scheduled`, `reconciliation_stopped`, and `status_server_failed`.
3. Correlate issue-specific logs by `issue_id` and `issue_identifier`.
4. Correlate Codex session logs by `session_id` when it is present.
5. Confirm secrets are redacted before sharing logs outside the operator group.

The runtime intentionally keeps logs in stable `key=value` phrasing. If a log sink fails, the service should continue when possible and emit an operator-visible warning through the remaining sink.

Configure runtime-owned sinks with `logging.level`, `logging.console`, and `logging.file` in `WORKFLOW.md`. Relative log file paths resolve from the workflow directory. A valid workflow reload updates runtime-owned handlers without removing handlers installed by the host process or tests.

## Failure Modes

Use this table to choose the first recovery action.

| Symptom | Likely cause | First action |
|---|---|---|
| Runtime exits before polling | Missing workflow, invalid config, missing tracker auth, or missing project slug | Run `harness run WORKFLOW.md` locally and fix the startup error. |
| No new work dispatches | Dispatch preflight failure, no active candidates, blockers, or concurrency exhausted | Check logs for `dispatch_preflight_failed`, then inspect active states and `max_concurrent_agents`. |
| Running work stops after tracker edit | Issue became terminal or non-active | Confirm the tracker state change was intentional; terminal states clean workspaces, non-active states preserve them. |
| Repeated retries | Codex failure, hook failure, timeout, or tracker candidate fetch issue | Check latest run attempt status and retry error through `/api/v1/<issue_identifier>`. |
| Workspace hook hangs | Hook timeout too high or shell command waiting for input | Keep hooks non-interactive and tune `hooks.timeout_ms`. |
| User input requested by Codex | Runtime policy treats user input required as a run failure | Update the issue or repository instructions so the agent can proceed without waiting. |

When in doubt, pause dispatch by making active states empty or moving candidate issues out of active states, then inspect logs and workspaces before restarting.

## Dashboard And API Operation

Use this when observing live state or forcing an immediate poll.

1. Enable the status API with `server.port` in `WORKFLOW.md` or `harness run --port PORT WORKFLOW.md`.
2. Keep the bind host loopback unless you have a deployment-specific reason to expose it.
3. Open `/` for a human-readable summary.
4. Use `GET /api/v1/state` for running sessions, retry queue, token totals, runtime seconds, and rate limits.
5. Use `GET /api/v1/<issue_identifier>` for issue-specific running, retry, and latest attempt details.
6. Use `POST /api/v1/refresh` to queue one immediate poll and reconciliation cycle. Repeated requests coalesce until the service loop consumes the refresh flag.

Listener settings do not hot-rebind. Restart the runtime after changing `server.host`, `server.port`, or CLI `--port`.

## SPEC Compatibility Upgrades

Use this when `SPEC.md`, the targeted Codex app-server protocol, or Linear behavior changes.

1. Read the restored local `SPEC.md` first; treat it as normative for this repository.
2. Update `docs/runtime/spec-conformance-matrix.md` before or alongside behavior changes so implementation status stays visible.
3. Add or adjust TODO items in `docs/runtime/spec-conformance-todo.md` before continuing unrelated work.
4. Keep Codex protocol envelope changes inside `harness/runtime/agent.py`.
5. Keep Linear GraphQL shape and error mapping changes inside `harness/runtime/tracker.py` or the `linear_graphql` client tool.
6. Run `make test`, `make validate`, `make stale-design-check`, and `git diff --check`.
7. For production readiness, follow `docs/runtime/production-readiness-checklist.md`, including the gated integration profile and Codex schema verification when applicable.

Do not use upstream Symphony implementation code as the runtime path. Upstream links and skills can remain reference material, while behavior should be implemented and tested in this repository.
