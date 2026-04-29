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

```bash
python -m harness.cli init --target /path/to/your/repo --profile cautious-linear
python -m harness.cli validate --target /path/to/your/repo
```

Then configure `/path/to/your/repo/WORKFLOW.md` and run the hardened runtime:

```bash
python -m harness.cli run --workflow /path/to/your/repo/WORKFLOW.md
```

## Documentation

Start with `docs/README.md`.

Runtime compatibility is tracked against the upstream [Symphony service specification](https://github.com/openai/symphony/blob/main/SPEC.md). Upstream implementation code is reference material only.

The runtime is in an early conformance stage: orchestration boundaries, validation, retries, and workspace safety are covered by tests, while full Codex app-server protocol integration remains isolated behind the runner abstraction.

## Status

Early hardened runtime scaffold. Use least-privilege credentials and human review gates first.
