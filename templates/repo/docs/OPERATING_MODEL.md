# Operating Model

Humans manage work. Agents execute bounded issues. The issue tracker is the control plane.

## States

- `Todo`: eligible for pickup.
- `In Progress`: agent or human is working.
- `Rework`: output needs fixes.
- `Human Review`: ready for human review.
- `Merging`: accepted and ready to land.
- `Done`: complete.
- `Cancelled` and `Duplicate`: terminal.

## Handoff

Ready work should include a pull request, test evidence, CI status when available, risks, and follow-ups.

## Failure Policy

When an agent fails repeatedly, improve the issue, docs, tests, setup, or workflow prompt.
