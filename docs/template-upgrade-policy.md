# Template Upgrade Policy

`harness init` is copy-only. It creates or overwrites scaffold files in a target repository, but it does not track which scaffold version produced those files and does not perform in-place upgrades.

## Supported Upgrade Path

Use this process when a target repository already adopted the scaffold and wants newer template content.

1. Read the scaffold release notes and compatibility policy before copying anything.
2. Compare the current target repository files with `templates/repo/`.
3. Copy only the template changes that are useful for that target repository.
4. Preserve target-specific edits in `AGENTS.md`, `WORKFLOW.md`, docs, hooks, skills, and CI.
5. Run `python3 -m harness.cli validate --target <target-repo>`.
6. Commit the selected target-repo changes with a note that they were manually adopted from this scaffold.

## `--force` Policy

`python3 -m harness.cli init --force` is appropriate only for disposable targets, brand-new repositories, or deliberate full regeneration after reviewing the overwrite list.

Do not use `--force` as an upgrade mechanism for an existing adopted repository. It can overwrite project-owned instructions, workflow configuration, runbooks, CI, and local skills.

## Non-Support Statement

This scaffold version does not provide a `harness upgrade` command. Automatic three-way merging, scaffold provenance tracking, and migration scripts for generated target repositories are intentionally out of scope until they are designed and tested explicitly.
