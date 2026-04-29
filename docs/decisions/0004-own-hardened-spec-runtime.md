# 0004 Own Hardened SPEC Runtime

## Status

Accepted

## Decision

This repository owns a hardened Python runtime compatible with the upstream Symphony service specification.

The runtime must not depend on upstream implementation code. Upstream `SPEC.md` is the normative reference for behavior, and upstream `.codex/skills` may be copied or adapted as agent guidance with attribution.

## Safety Posture

- Workspace paths must remain under the configured workspace root.
- Coding-agent commands must run only in the per-issue workspace.
- Workflow config is validated before dispatch.
- Secrets are supplied through explicit environment indirection and are not logged.
- Approval and user-input-required events must not stall indefinitely.
- Structured logs must expose startup, validation, dispatch, retry, and session failures.
- Human review remains required before merge unless a target project explicitly adopts stronger gates.
