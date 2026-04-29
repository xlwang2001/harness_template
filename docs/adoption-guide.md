# Adoption Guide

This guide explains how to adopt the harness scaffold in an existing project.

## Prerequisites

You need a Git repository, a working local setup command, at least one automated test command, Codex installed and authenticated, a supported issue tracker, and a hardened environment for running coding agents.

## Initialize

```bash
python -m harness.cli init --target /path/to/your/repo --profile cautious-linear
```

Inspect the generated files before committing them.

## Fill Project-Specific Guidance

Edit `AGENTS.md`, `WORKFLOW.md`, `ARCHITECTURE.md`, and the docs under `docs/`. Keep `AGENTS.md` short and put durable knowledge in the deeper docs.

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
python -m harness.cli validate --target /path/to/your/repo
```

Fix errors before running the hardened runtime.

## First Smoke Test

Create a low-risk issue such as: "Update docs/README.md to add one sentence explaining the local development command." Confirm that the runtime creates a workspace, starts Codex, produces a PR or patch, and leaves a review packet.
