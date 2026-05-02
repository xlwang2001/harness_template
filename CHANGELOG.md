# Changelog

## 1.0.0

Initial Linear-first hardened runtime release.

### Implemented

- Added the standard-library CLI for `init`, `validate`, `run`, and `runtime-check`.
- Added target-repository templates, validators, human operating docs, examples, CI, ADRs, and compatibility policies.
- Implemented the in-repo hardened Python runtime aligned with the upstream Symphony service specification.
- Added Linear issue polling, normalization, read APIs, explicit write APIs, and the constrained `linear_graphql` request-time tool.
- Added orchestrator dispatch, bounded concurrency, retries, reconciliation, stall detection, graceful shutdown, and run-attempt lifecycle tracking.
- Added workspace sanitization, root containment, lifecycle hooks, terminal cleanup, and preserved workspace reuse.
- Added Codex app-server launch, schema-aligned request/response handling, thread/turn startup, continuation turns, event aggregation, timeout mapping, approval/user-input policy, and client-tool handling.
- Added structured logs, configurable console/file sinks, loopback HTTP status API, runtime snapshots, durable scheduler-safe runtime state, and gated integration profiles.

### Known Deferred Or Blocked Items

- `linear_graphql` startup advertisement is schema-blocked until the targeted Codex generated schema exposes a stable client-tool advertisement field.
- Non-Linear tracker adapters are deferred for Linear-only deployments and should be revisited only for a concrete tracker target.
- Real Linear mutation integration remains separately gated and placeholder-only to avoid accidental writes to production projects.
- Advanced workspace population, remote checkout, and remote execution remain future hardening and are not required for current Linear local-workspace use.

### Verification

- Default tests and scaffold validation are expected to pass without credentials or network access.
- Before unattended production use, run the production readiness checklist, including `make codex-schema-test` for the installed Codex app-server version and the gated real integration profile with the intended Linear project.
