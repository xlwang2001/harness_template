# Changelog

## 1.4.0

Installable package release.

### Added

- Made `harness-engineering-starter` build as an installable wheel with the hardened runtime, CLI, validators, profiles, and scaffold templates included.
- Added packaged template resources so `harness init` works after installing from a private package index without cloning this repository.
- Added package verification coverage for building a wheel, installing it into a temporary virtual environment, and running the installed `harness` command.

### Verification

- The installed CLI can run `harness --help`, dry-run template initialization, create a target repository, and validate the generated target without a source checkout.

## 1.3.1

Workflow YAML subset visibility release.

### Added

- Made the supported `WORKFLOW.md` YAML subset visible in repo and runtime workflow templates.
- Documented unsupported YAML constructs in adoption and runtime docs.
- Added scaffold validation warnings for anchors, aliases, merge keys, custom tags, and folded `>` scalars in workflow front matter.

### Verification

- Runtime behavior is unchanged; this patch release makes parser boundaries visible before unsupported YAML reaches production workflows.

## 1.3.0

Adopted example release.

### Added

- Added `examples/adopted-tiny-cli/`, a complete target-repository example with harness docs, workflow, skills, scripts, sample issue, sample review packet, and working CLI tests.
- Linked the adopted example from the adoption guide.

### Verification

- The adopted example validates with the scaffold validators and its sample review packet passes review packet validation.

## 1.2.0

Machine-checkable review packet release.

### Added

- Added review packet Markdown and JSON schema templates for generated target repositories.
- Added `harness validate-review-packet --path PATH` for Markdown section checks and optional sibling JSON validation.
- Updated the review-packet skill, PR template, and review guide to point humans and agents at the review packet contract.

### Verification

- Review packet validation is opt-in and does not make ordinary scaffold validation require completed packets.

## 1.1.0

Dispatch preview release.

### Added

- Added `harness dispatch-preview --workflow WORKFLOW.md [--limit N]` for read-only candidate dispatch previews.
- Preview output includes resolved config, candidate order, eligibility reasons, workspace paths, and truncated prompt previews without creating workspaces, launching Codex, or mutating tracker state.
- Documented dispatch preview in the adoption guide and runtime runbooks.

### Verification

- Default tests remain credential-free; real Linear use is still read-only unless a separately gated mutation profile is implemented later.

## 1.0.1

Runtime support matrix release.

### Added

- Added `docs/runtime/support-matrix.md` so adopters can quickly distinguish supported, unsupported, deferred, schema-blocked, and verification-required runtime capabilities.
- Linked the support matrix from README, adoption, runtime, and production-readiness docs.

### Verification

- No runtime behavior changed in this patch release.

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
