---
# WORKFLOW.md front matter uses the harness YAML subset:
# nested maps, "- " lists, quoted/unquoted scalars, comments, and | block scalars.
# Avoid anchors, aliases, merge keys, custom tags, folded > scalars, and complex YAML expressions.
tracker:
  kind: {{ profile.tracker_kind }}
  api_key: $LINEAR_API_KEY
  project_slug: "$LINEAR_PROJECT_SLUG"
  active_states:
{{ profile.active_states_yaml }}
  terminal_states:
{{ profile.terminal_states_yaml }}
  handoff_state: "{{ profile.human_review_state }}"

workspace:
  root: "{{ profile.workspace_root }}"

hooks:
  after_create: |
    git clone "$SOURCE_REPO_URL" .
    ./scripts/bootstrap-agent-workspace.sh
  before_run: |
    ./scripts/pre-agent-run.sh
  after_run: |
    ./scripts/post-agent-run.sh

agent:
  max_concurrent_agents: {{ profile.max_concurrent_agents }}
  max_turns: {{ profile.max_turns }}
  max_retry_backoff_ms: 300000

codex:
  command: "codex app-server"
---

You are working on issue {{ issue.identifier }}.

Title:
{{ issue.title }}

Description:
{{ issue.description }}

Profile:
{{ profile.name }} - {{ profile.notes }}

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
- Move ready work to {{ profile.human_review_state }} when the project workflow supports state transitions.
- If the issue is ambiguous or unsafe, comment on the issue and request human review.
