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

The runtime has a hardened orchestration boundary and conformance tests, and `CodexAgentRunner` now owns app-server launch, session/thread/turn startup, event streaming, timeout handling, and terminal error mapping. `SPEC.md` intentionally defers exact protocol envelopes to the targeted Codex app-server version, so production use should verify the adapter against the generated schema for the installed Codex version and run real tracker smoke tests before unattended operation.

User-input-required events fail the current run immediately as `turn_input_required`; the orchestrator then applies the normal retry policy. This keeps runs from waiting indefinitely for operator input.

## Workflow Front Matter Subset

The standard-library parser intentionally supports a documented YAML subset: nested maps by indentation, lists with `- ` items, quoted or unquoted scalars, integers, booleans, null values, comments, blank lines, and `|` block scalars. Unsupported YAML features should fail parsing instead of being guessed. This subset covers scaffold `WORKFLOW.md` templates while keeping dependency policy explicit.

## Reference Material

The upstream Symphony repository remains useful for its service specification and `.codex/skills`. Its implementation code is not used as this runtime's execution path.
