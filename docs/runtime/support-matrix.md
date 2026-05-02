# Runtime Support Matrix

This document defines the current support boundary for the 1.0 hardened runtime.

| Area | Status | Notes |
|---|---|---|
| Linear tracker | Supported | Primary production tracker target. Run the gated Linear integration profile before unattended use. |
| GitHub Issues tracker | Not supported | Deferred until there is a concrete deployment target. |
| Jira / Shortcut trackers | Not supported | Deferred until there is a concrete deployment target. |
| Codex app-server runner | Supported with schema verification | Run `make codex-schema-test` after Codex upgrades. |
| `linear_graphql` request-time tool handling | Supported | Available when Codex app-server requests the tool through the supported protocol. |
| `linear_graphql` startup advertisement | Schema-blocked | Deferred until Codex generated schema exposes a stable client-tool advertisement field. |
| Auto-merge | Not supported by default | Require human review gates unless project policy explicitly changes this. |
| Multi-process distributed leasing | Not supported | Current runtime assumes local orchestrator ownership. |
| Durable local runtime state | Supported | Scheduler-safe metadata only; no live process ownership restoration. |
| Production credentials in workspaces | Discouraged | Use least-privilege, short-lived credentials and avoid mounting production secrets. |
| UI/browser proof-of-work | Template-level only | Add project-specific tooling and evidence requirements if needed. |
| Network access during agent runs | Project-policy dependent | Document the policy in `WORKFLOW.md` and security docs. |
| Remote checkout / remote execution | Future hardening | Not required for current Linear local-workspace use. |

Use `docs/runtime/production-readiness-checklist.md` before first production use.
