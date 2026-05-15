# Adoption Guide

This guide explains how to adopt the harness scaffold in an existing project.

## Prerequisites

You need a Git repository, a working local setup command, at least one automated test command, Codex installed and authenticated, a supported issue tracker, and a hardened environment for running coding agents.

Install the scaffold package from your private package index before adopting it:

```bash
pipx install harness-engineering-starter --index-url <PRIVATE_INDEX_URL>
```

If `pipx` is not available, use:

```bash
python -m pip install harness-engineering-starter --index-url <PRIVATE_INDEX_URL>
```

You do not need to clone the scaffold repository unless you are developing the scaffold itself.

## Initialize

```bash
harness init --target /path/to/your/repo --profile cautious-linear
```

Inspect the generated files before committing them.

Before first live runtime use, review `docs/runtime/support-matrix.md` so the current Linear-first support boundary is clear.

The generated GitHub Actions validation workflow installs the harness package from:

```text
git+https://github.com/xlwang2001/harness_template.git@main
```

That default tracks the latest `main` commit. For reproducible CI, set the repository variable `HARNESS_PACKAGE_SPEC` to a pinned tag, commit SHA, wheel URL, or package-index spec when your project is ready to pin.

## Fill Project-Specific Guidance

Edit `AGENTS.md`, `WORKFLOW.md`, `ARCHITECTURE.md`, and the docs under `docs/`. Keep `AGENTS.md` short and put durable knowledge in the deeper docs.

`WORKFLOW.md` front matter uses a deliberately small YAML subset: nested maps, `- ` lists, quoted or unquoted scalars, comments, and `|` block scalars. Avoid anchors, aliases, merge keys, custom tags, folded `>` scalars, and complex YAML expressions; `harness validate` warns when it sees unsupported constructs.

Set `tracker.handoff_state` to the exact Linear workflow state that should receive completed agent work, for example `handoff_state: "Human Review"`. This value is a single scalar string, not a list. Keep the handoff state out of `active_states` so the runtime does not immediately pick the issue up again after a successful handoff.

## Configure Environment

```bash
export LINEAR_API_KEY=...
export LINEAR_PROJECT_SLUG=...
export SOURCE_REPO_URL=git@github.com:your-org/your-repo.git
export SYMPHONY_WORKSPACE_ROOT=~/code/symphony-workspaces/your-repo
```

Do not commit secrets.

## Validate

```bash
harness validate --target /path/to/your/repo
```

Fix errors before running the hardened runtime.

## Preview Dispatch

Before the first live run, preview candidate selection without creating workspaces or launching Codex:

```bash
harness dispatch-preview --workflow /path/to/your/repo/WORKFLOW.md
```

Confirm the eligible issues, skipped reasons, prompt preview, and workspace paths match the intended project policy.

## First Smoke Test

Create a low-risk issue such as: "Update docs/README.md to add one sentence explaining the local development command." Confirm that the runtime creates a workspace, starts Codex, produces a PR or patch, leaves a review packet, and transitions the issue to the configured handoff state.

For a complete adopted target repository shape, inspect `examples/adopted-tiny-cli/`.
