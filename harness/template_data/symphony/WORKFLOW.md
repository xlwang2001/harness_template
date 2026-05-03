---
# WORKFLOW.md front matter uses the harness YAML subset:
# nested maps, "- " lists, quoted/unquoted scalars, comments, and | block scalars.
# Avoid anchors, aliases, merge keys, custom tags, folded > scalars, and complex YAML expressions.
tracker:
  kind: linear
  api_key: $LINEAR_API_KEY
  project_slug: "$LINEAR_PROJECT_SLUG"
  active_states:
    - Todo
    - In Progress
    - Rework
  terminal_states:
    - Done
    - Closed
    - Cancelled
    - Canceled
    - Duplicate

workspace:
  root: "$SYMPHONY_WORKSPACE_ROOT"

hooks:
  after_create: |
    git clone "$SOURCE_REPO_URL" .
    ./scripts/bootstrap-agent-workspace.sh
  before_run: |
    ./scripts/pre-agent-run.sh
  after_run: |
    ./scripts/post-agent-run.sh

agent:
  max_concurrent_agents: 4
  max_turns: 20
  max_retry_backoff_ms: 300000

codex:
  command: "codex app-server"
---

You are working on Linear issue {{ issue.identifier }}.

Title:
{{ issue.title }}

Description:
{{ issue.description }}

Objective:
Complete the issue in this repository using the project guidance in AGENTS.md and docs/.

Operating rules:

- Work in the current workspace only.
- Read AGENTS.md first.
- Use docs/README.md as the knowledge map.
- Prefer existing project patterns.
- Run relevant tests.
- Create or update a pull request when the work is ready.
- Leave evidence: test results, CI status, and a concise review packet.
- If the issue is ambiguous or unsafe, comment on the issue and move it to Human Review or Rework according to the project operating model.
