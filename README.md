# Harness Engineering Starter

A reusable scaffold and hardened SPEC-compatible runtime for agent-friendly software projects with Codex.

This repository implements a hardened Python runtime compatible with the upstream Symphony service specification and adds the project-engineering layer around it:

- target repo templates,
- `AGENTS.md` and `WORKFLOW.md` conventions,
- repository knowledge-base structure,
- human operating docs,
- issue-writing and review guides,
- validation scripts,
- hardened workspace and orchestration runtime,
- example projects.

## Philosophy

Humans steer. Agents execute.

The issue tracker is the control plane. The repository is the knowledge system of record. The in-repo hardened runtime runs agents according to a `WORKFLOW.md` contract.

## Quick Start

Install the scaffold from your private package index:

```bash
pipx install harness-engineering-starter --index-url <PRIVATE_INDEX_URL>
```

Or with `pip`:

```bash
python -m pip install harness-engineering-starter --index-url <PRIVATE_INDEX_URL>
```

Ordinary adopters do not need to clone this scaffold repository. After installation, use the `harness` command:

```bash
harness init --target /path/to/your/repo --profile cautious-linear
harness validate --target /path/to/your/repo
```

Then configure `/path/to/your/repo/WORKFLOW.md` and run the hardened runtime:

```bash
harness run --workflow /path/to/your/repo/WORKFLOW.md
```

Clone this repository only when developing the scaffold itself.

When maintaining this scaffold repository, use the Makefile checks from a source checkout:

```bash
make test
make runtime-check
make package-check
```

## Documentation

Start with `docs/README.md`.

Runtime compatibility is tracked against the upstream [Symphony service specification](https://github.com/openai/symphony/blob/main/SPEC.md). Upstream implementation code is reference material only.

Runtime support boundaries are summarized in `docs/runtime/support-matrix.md`.

Release history lives in `CHANGELOG.md`.

The 1.0 runtime is a Linear-first hardened scaffold: orchestration boundaries, validation, retries, workspace safety, Linear integration, observability, durable runtime state, and the Codex app-server runner boundary are covered by tests. The exact app-server envelopes remain isolated behind `CodexAgentRunner` and should be verified against the generated schema for the installed Codex version before unattended production use.

## Status

1.0 Linear-first hardened runtime scaffold. Use least-privilege credentials, the production readiness checklist, and human review gates before unattended production use.
