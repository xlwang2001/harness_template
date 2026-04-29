# Hardened Runtime

This runtime follows the upstream [Symphony service specification](https://github.com/openai/symphony/blob/main/SPEC.md) while keeping implementation and safety policy in this repository.

## Core Components

- Workflow loader and config resolver
- Linear-compatible issue tracker adapter
- Workspace manager with path containment checks
- Orchestrator with polling, reconciliation, retries, and bounded concurrency
- Codex app-server runner abstraction
- Structured runtime snapshot state

## Current Limitations

The runtime has a hardened orchestration boundary and conformance tests, but the Codex app-server protocol client is still intentionally isolated behind `CodexAgentRunner`. Production use should complete protocol-level integration and real tracker smoke tests before unattended operation.

## Workflow Front Matter Subset

The standard-library parser intentionally supports a documented YAML subset: nested maps by indentation, lists with `- ` items, quoted or unquoted scalars, integers, booleans, null values, comments, blank lines, and `|` block scalars. Unsupported YAML features should fail parsing instead of being guessed. This subset covers scaffold `WORKFLOW.md` templates while keeping dependency policy explicit.

## Reference Material

The upstream Symphony repository remains useful for its service specification and `.codex/skills`. Its implementation code is not used as this runtime's execution path.
