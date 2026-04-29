# 0001 Reuse Symphony As Submodule

## Status

Accepted

## Decision

This scaffold pins Symphony as a git submodule under `vendor/symphony`.

## Rationale

The scaffold owns templates, docs, validators, examples, and operating practices. Symphony owns orchestration runtime behavior. A submodule keeps the boundary clear, permits deliberate upgrades, and avoids copying runtime code into this repository.
