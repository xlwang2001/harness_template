# 0001 Reuse Symphony As Submodule

## Status

Superseded by `0004-own-hardened-spec-runtime.md`

## Decision

This scaffold originally pinned Symphony as a git submodule under `vendor/symphony`.

## Rationale

This was useful for the initial scaffold baseline, but it left the runtime safety posture outside this repository. The current design owns a hardened SPEC-compatible runtime in Python and treats upstream material as reference input only.
