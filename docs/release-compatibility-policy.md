# Release And Compatibility Policy

This policy describes how scaffold changes should affect repositories generated from `templates/repo/`.

## Version Expectations

- Patch releases should not require generated target repositories to change.
- Minor releases may add templates, validators, examples, docs, or optional runtime config.
- Major releases may change adoption layout, generated file names, workflow shape, or compatibility guarantees.

## Compatibility Guarantees

- Existing generated repositories remain project-owned after `harness init`.
- Template changes are not automatically applied to adopted repositories.
- Validators should prefer actionable warnings for new guidance unless correctness or safety requires an error.
- Runtime workflow config should keep documented defaults stable across patch releases.
- Generated docs should remain readable Markdown and avoid repo-specific assumptions unless profiles provide them.

## Release Notes Requirements

Every release note should call out:

- template files added, removed, renamed, or substantially rewritten;
- validator changes, especially new errors;
- runtime workflow config changes, defaults, or deprecations;
- manual adoption steps for existing generated repositories;
- breaking changes that require a major version.

## Generated Repository Policy

Generated repositories should pin or record the scaffold version they adopted in their own project history if they need auditability. The scaffold does not infer that version later.

When a generated repository adopts a newer scaffold pattern, treat the change as a normal project change: review the diff, update local docs, and run validation in that repository.
