# Maintaining This Scaffold

The scaffold maintainers own templates, docs, validators, examples, the hardened SPEC-compatible runtime, upgrade notes, and release notes. They do not own project-specific business logic copied into target repos.

## Updating The Runtime Against The Spec

Use the upstream Symphony service specification as the compatibility reference. When the spec changes, update the in-repo runtime, tests, and compatibility notes together.

The upstream repository's `.codex/skills` may be used as reference guidance, but runtime behavior belongs in this repository.

## Compatibility Policy

Patch releases should not break generated target repos. Minor releases may add templates or validators. Major releases may change adoption layout.

Detailed policy lives in `docs/release-compatibility-policy.md`.

Before tagging runtime-facing releases, follow `docs/runtime/production-readiness-checklist.md` so gated integration and Codex schema checks are recorded deliberately.

## Updating Generated Target Repos

`harness init` is copy-only and does not perform in-place upgrades of adopted target repositories. Use the manual process in `docs/template-upgrade-policy.md` when a target repository wants newer template content.
