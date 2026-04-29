# Harness Engineering Starter

A reusable scaffold for building agent-friendly software projects with Codex and Symphony.

This repository does not reimplement Symphony. It vendors Symphony as an upstream runtime and adds the project-engineering layer around it:

- target repo templates,
- `AGENTS.md` and `WORKFLOW.md` conventions,
- repository knowledge-base structure,
- human operating docs,
- issue-writing and review guides,
- validation scripts,
- example projects.

## Philosophy

Humans steer. Agents execute.

The issue tracker is the control plane. The repository is the knowledge system of record. Symphony runs the agents. This scaffold makes projects ready for that operating model.

## Quick Start

```bash
git submodule update --init --recursive
python -m harness.cli init --target /path/to/your/repo --profile cautious-linear
python -m harness.cli validate --target /path/to/your/repo
```

Then configure `/path/to/your/repo/WORKFLOW.md` and run Symphony:

```bash
python -m harness.cli run --workflow /path/to/your/repo/WORKFLOW.md
```

## Documentation

Start with `docs/README.md`.

## Status

Early scaffold. Use in trusted environments first.
