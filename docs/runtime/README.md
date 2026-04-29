# Hardened Runtime

This runtime follows the upstream [Symphony service specification](https://github.com/openai/symphony/blob/main/SPEC.md) while keeping implementation and safety policy in this repository.

## Core Components

- Workflow loader and config resolver
- Linear-compatible issue tracker adapter
- Workspace manager with path containment checks
- Orchestrator with polling, reconciliation, retries, and bounded concurrency
- Codex app-server runner abstraction
- Structured runtime snapshot state

## Reference Material

The upstream Symphony repository remains useful for its service specification and `.codex/skills`. Its implementation code is not used as this runtime's execution path.
