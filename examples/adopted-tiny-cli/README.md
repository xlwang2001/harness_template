# Adopted Tiny CLI

This example shows the shape of a small repository after adopting the harness scaffold.

## Local Commands

```sh
python -m unittest discover -s tests
python tiny_cli.py report
python tiny_cli.py report --json
```

## Harness Files

- `AGENTS.md` gives short agent entry instructions.
- `WORKFLOW.md` defines the runtime contract.
- `docs/` contains durable project knowledge.
- `docs/sample-issues/add-json-output.md` shows an agent-ready issue.
- `docs/exec-plans/completed/ABC-123/review-packet.md` shows expected proof of work.
