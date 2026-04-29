# Maintaining This Scaffold

The scaffold maintainers own templates, docs, validators, examples, Symphony pinning, upgrade notes, and release notes. They do not own project-specific business logic copied into target repos.

## Updating Symphony

```bash
git -C vendor/symphony fetch origin
git -C vendor/symphony log --oneline HEAD..origin/main
git -C vendor/symphony checkout <new-commit>
git add vendor/symphony
make validate
make test
```

Update compatibility notes before release.

## Compatibility Policy

Patch releases should not break generated target repos. Minor releases may add templates or validators. Major releases may change adoption layout.
