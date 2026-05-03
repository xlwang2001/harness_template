---
tracker:
  kind: linear
  api_key: $LINEAR_API_KEY
  project_slug: "$LINEAR_PROJECT_SLUG"
  active_states:
    - Todo
    - In Progress
  terminal_states:
    - Done
    - Cancelled

workspace:
  root: "/tmp/adopted-tiny-cli-workspaces"

hooks:
  after_create: |
    sh ./scripts/bootstrap-agent-workspace.sh
  before_run: |
    sh ./scripts/pre-agent-run.sh
  after_run: |
    sh ./scripts/post-agent-run.sh

agent:
  max_concurrent_agents: 1
  max_turns: 3
  max_retry_backoff_ms: 300000

codex:
  command: "codex app-server"
---

You are working on issue {{ issue.identifier }}.

Title:
{{ issue.title }}

Description:
{{ issue.description }}

Complete the issue in this repository using AGENTS.md and docs/README.md.

Run `python -m unittest discover -s tests`, update docs when behavior changes, and leave a review packet before handoff.
