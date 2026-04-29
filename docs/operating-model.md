# Operating Model

Humans manage work. Agents execute work. The issue tracker is the control plane.

## Roles

Product owners write or approve issues, clarify acceptance criteria, and review user-facing behavior.

Engineers maintain repo harness quality, review code and architecture, improve tests and docs when agents fail, and handle high-judgment tasks directly.

Agents read the issue, read `AGENTS.md` and relevant docs, make changes in an isolated workspace, run tests, open or update a PR, and leave proof of work.

## Workflow States

- `Todo`: eligible for agent pickup.
- `In Progress`: agent or human is working.
- `Rework`: previous output needs fixes.
- `Human Review`: agent believes work is ready.
- `Merging`: work is accepted and should be landed.
- `Done`: work is complete.
- `Cancelled` / `Duplicate`: terminal states.

## Failure Policy

When an agent fails, ask whether the issue was unclear, repo knowledge was missing, tests were insufficient, setup was fragile, or the workflow prompt was wrong. Repeated failures should improve the harness.
