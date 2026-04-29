# Symphony-oriented Harness Engineering Scaffold: Implementation Plan

Date: 2026-04-29
Audience: maintainers who want to build a reusable repository for project engineering with Codex/Symphony-style orchestration
Bias: prefer Symphony-style issue-centric orchestration over Superteam-style rigid planning/execution state machines

---

## 0. Executive summary

Build a repository that acts as a reusable **harness engineering scaffold** for agent-first project engineering.

This repository should:

1. **Implement a hardened SPEC-compatible Symphony runtime** in this repository, using upstream `SPEC.md` as the normative reference.
2. Provide **templates** that make an application repository agent-legible:
   - `AGENTS.md` as a short table of contents, not a giant manual.
   - `WORKFLOW.md` as the Symphony runtime contract.
   - structured `docs/` as the project knowledge system of record.
   - Codex skills, hooks, and validation scripts where useful.
3. Provide **human-facing operating documentation**:
   - how to adopt the scaffold in a new project,
   - how to write issues for agent execution,
   - how to review agent output,
   - how to maintain repository-local knowledge,
   - how to operate Symphony safely.
4. Provide **validation and smoke tests**:
   - check that target repos contain the right docs,
   - check that `WORKFLOW.md` is valid,
   - check that the target project exposes sufficient tests and proof-of-work hooks.
5. Provide **thin developer tooling**:
   - `harness init`,
   - `harness validate`,
   - `harness run`,
   - `harness runtime-check`.

The core product is not “another orchestrator”; it is a **repeatable operating system for making project repos usable by autonomous coding agents**.

---

## 1. Source principles

### 1.1 Humans steer; agents execute

The repo should help humans specify intent, constraints, and review criteria, then let agents execute in bounded workspaces.

### 1.2 Issue tracker as control plane

Use Symphony’s model: issues or tickets represent work. Symphony polls eligible issues, creates per-issue workspaces, launches Codex, and keeps work moving until the workflow reaches a handoff state.

### 1.3 Repository knowledge is the system of record

Do not rely on Slack threads, Google Docs, or tacit knowledge. Put the durable information into the repo: product specs, architecture notes, design decisions, execution plans, quality scorecards, reliability/security rules, generated references, and runbooks.

### 1.4 `AGENTS.md` is a map, not a manual

Keep `AGENTS.md` short. It should point Codex to deeper docs rather than trying to contain everything.

### 1.5 Do not overfit agents into rigid state machines

Unlike Superteam, this scaffold should avoid overly narrow “planner → implementer → reviewer” choreography. The orchestration layer should be mechanical; the coding agent should receive an objective, tools, repo context, and quality gates.

### 1.6 Proof of work matters

Every agent run should produce evidence: CI status, test commands and results, PR link, review feedback, screenshots or video walkthroughs when UI changes, logs/traces/metrics when reliability or performance matters.

---

## 2. Non-goals

This scaffold should **not** do the following in the first version:

- Reimplement Symphony’s scheduler, Linear polling, Codex app-server runner, or dashboard.
- Become a general-purpose workflow engine.
- Force one universal security posture across all teams.
- Replace human review.
- Hide the fact that Symphony is an reference implementation and should be hardened before unattended use.
- Implement Superteam’s rigid planning/execution/review role split as the primary philosophy.

---

## 3. Recommended repository shape

```text
harness-engineering-starter/
  README.md
  LICENSE
  Makefile
  pyproject.toml
  .gitmodules


  harness/
    __init__.py
    cli.py                             # init / validate / run hardened runtime
    templates.py
    workflow_validator.py
    docs_validator.py
    project_profiles.py

  templates/
    repo/
      AGENTS.md
      WORKFLOW.md
      ARCHITECTURE.md
      docs/
        README.md
        PRODUCT.md
        ENGINEERING.md
        QUALITY.md
        RELIABILITY.md
        SECURITY.md
        OPERATING_MODEL.md
        design-docs/
          index.md
          0000-template.md
        exec-plans/
          active/README.md
          completed/README.md
          tech-debt-tracker.md
        product-specs/
          index.md
          0000-template.md
        generated/README.md
        runbooks/
          local-dev.md
          ci-debugging.md
          release.md
      .agents/
        skills/
          ci-debugger/SKILL.md
          review-packet/SKILL.md
          doc-gardener/SKILL.md
      .codex/
        hooks/
          pre_tool_use_policy.py
          post_tool_use_summary.py
          stop_validate_artifacts.py
        config.example.toml
      .github/
        pull_request_template.md
        workflows/harness-docs.yml

    symphony/
      WORKFLOW.md
      env.example
      launch-local.sh
      launch-dashboard.sh

  docs/
    README.md
    adoption-guide.md
    operating-model.md
    issue-writing-guide.md
    review-guide.md
    knowledge-base-guide.md
    trust-and-safety.md
    maintaining-this-scaffold.md
    decisions/
      0001-reuse-symphony-as-submodule.md  # historical, superseded by 0004
      0004-own-hardened-spec-runtime.md
      0002-use-repo-knowledge-as-system-of-record.md
      0003-avoid-rigid-superteam-style-state-machines.md

  examples/
    tiny-cli/
    tiny-webapp/

  tests/
    test_workflow_template.py
    test_docs_contract.py
    test_scaffold_init.py
```

---

## 4. Hardened runtime strategy

### 4.1 Default: implement the SPEC in this repository

```bash
python -m harness.cli run --workflow /path/to/repo/WORKFLOW.md
```

Why:

- own the runtime safety posture directly;
- track upstream SPEC changes deliberately;
- update conformance tests deliberately;
- keep this repo focused on templates, docs, validation, adoption, and hardened orchestration.

### 4.2 Upstream reference material

Use upstream material only as reference input:

- non-Linear tracker support before upstream supports it;
- hardened sandbox behavior;
- different workspace lifecycle semantics;
- organization-specific auth;
- custom observability integration;
- dashboard changes.

Upstream implementation code is not an execution dependency. Upstream `.codex/skills` may be copied or adapted as agent guidance with attribution.

### 4.3 What this scaffold owns

- target repo templates;
- human adoption docs;
- validation scripts;
- example project layouts;
- workflow prompt templates;
- optional Codex skills/hooks;
- operational playbooks.

### 4.4 What the hardened runtime owns

- issue polling;
- candidate selection;
- per-issue workspace creation;
- Codex app-server launching;
- bounded concurrency;
- retry/backoff;
- in-memory scheduler state;
- optional dashboard/status surface;
- runtime logs.

---

## 5. Target project after adoption

```text
target-project/
  AGENTS.md
  WORKFLOW.md
  ARCHITECTURE.md

  docs/
    README.md
    PRODUCT.md
    ENGINEERING.md
    QUALITY.md
    RELIABILITY.md
    SECURITY.md
    OPERATING_MODEL.md
    design-docs/
    exec-plans/
    product-specs/
    generated/
    runbooks/

  .agents/skills/
    ci-debugger/
    review-packet/
    doc-gardener/

  .codex/
    config.example.toml
    hooks/

  .github/
    pull_request_template.md
    workflows/harness-docs.yml
```

Important: the target project owns copied files after adoption. Updates should be applied intentionally through `harness upgrade`, not silently.

---

## 6. Implementation phases

### Phase 0 — Upstream pinning and design decisions

Goal: create the scaffold repo and formalize the reuse strategy.

Tasks:

1. Create repository.
2. Implement hardened SPEC-compatible runtime package.
3. Add ADRs:
   - `0001-reuse-symphony-as-submodule.md` as a superseded historical decision
   - `0004-own-hardened-spec-runtime.md`
   - `0002-use-repo-knowledge-as-system-of-record.md`
   - `0003-avoid-rigid-superteam-style-state-machines.md`
4. Add `Makefile` targets:
   - `make runtime-check`
   - `make stale-design-check`
   - `make validate`
   - `make test`
5. Add root `README.md` explaining purpose and non-goals.

Acceptance criteria:

- `harness run` starts the in-repo hardened runtime and validates startup config.
- README clearly says the repo includes a hardened SPEC-compatible runtime and scaffold.
- Decision records explain why the project owns the hardened runtime.
- No operational path depends on upstream implementation code.

### Phase 1 — Minimal scaffold CLI

Goal: implement a thin CLI to copy templates into a target repo and validate them.

Commands:

```bash
harness init --target /path/to/repo --profile cautious-linear
harness validate --target /path/to/repo
harness run --workflow /path/to/repo/WORKFLOW.md
harness runtime-check
```

Suggested implementation: use Python standard library first; avoid dependencies until needed.

Tasks:

1. Create `harness/cli.py`.
2. Implement template copying with overwrite protection.
3. Implement `--dry-run`.
4. Implement `--force` for explicit overwrite.
5. Implement profiles:
   - `cautious-linear`
   - `trusted-local`
   - `toy-example`
6. Implement validation:
   - required files exist,
   - `WORKFLOW.md` has valid front matter,
   - `AGENTS.md` stays short,
   - docs index links exist,
   - required runbooks exist.
7. Add tests for `init` and `validate`.

Acceptance criteria:

- Running `harness init` against an empty repo creates expected files.
- Running it twice does not overwrite without `--force`.
- `harness validate` gives actionable errors.
- CLI behavior is covered by tests.

### Phase 2 — Human-facing documentation

Goal: write docs humans need to use the scaffold effectively. These docs are part of the product.

Files:

```text
docs/
  README.md
  adoption-guide.md
  operating-model.md
  issue-writing-guide.md
  review-guide.md
  knowledge-base-guide.md
  trust-and-safety.md
  maintaining-this-scaffold.md
```

Acceptance criteria:

- A new maintainer can understand the system without reading agent prompts.
- A product manager can write a usable issue.
- An engineer can review an agent-generated PR.
- A project maintainer can adopt the scaffold in an existing repo.
- The docs explain what Symphony does and what this scaffold adds.

### Phase 3 — Target repo templates

Goal: create reusable templates that make a project repo agent-legible.

Core templates:

1. `templates/repo/AGENTS.md`
2. `templates/repo/WORKFLOW.md`
3. `templates/repo/docs/README.md`
4. `templates/repo/docs/PRODUCT.md`
5. `templates/repo/docs/ENGINEERING.md`
6. `templates/repo/docs/QUALITY.md`
7. `templates/repo/docs/RELIABILITY.md`
8. `templates/repo/docs/SECURITY.md`
9. `templates/repo/docs/OPERATING_MODEL.md`
10. `templates/repo/ARCHITECTURE.md`

Template philosophy:

- Keep `AGENTS.md` short.
- Make `docs/README.md` the navigation hub.
- Make `WORKFLOW.md` explicit about active states, handoff states, review expectations, and proof-of-work requirements.
- Use placeholders for project-specific setup.

### Phase 4 — Symphony workflow template

Goal: provide a production-like `WORKFLOW.md` template that runs with upstream Symphony.

Minimal skeleton:

```md
---
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
```

Acceptance criteria:

- A project can copy this `WORKFLOW.md` and fill env variables.
- The prompt is objective-based, not a rigid Superteam state machine.
- Handoff states are documented.

### Phase 5 — Review packet skill

Goal: provide a repo-local Codex skill that teaches agents what evidence humans expect.

File:

```text
templates/repo/.agents/skills/review-packet/SKILL.md
```

The skill should instruct Codex to produce:

- issue identifier;
- PR link;
- summary of intent;
- changed files;
- tests run;
- CI status;
- screenshots/video if relevant;
- known risks;
- review checklist;
- follow-up issues created.

### Phase 6 — Documentation and knowledge validators

Goal: mechanically enforce that the repo stays legible.

Validators:

1. `docs_validator.py`
   - checks required docs exist;
   - checks links in `docs/README.md`;
   - checks empty placeholder sections;
   - checks stale “TODO fill this in” markers.

2. `workflow_validator.py`
   - checks `WORKFLOW.md` front matter;
   - checks required tracker/workspace/agent keys;
   - checks prompt body contains issue variables;
   - checks env var references are documented in `.env.example`.

3. `agents_validator.py`
   - checks `AGENTS.md` length;
   - checks it links to docs;
   - checks it avoids huge embedded manuals.

Acceptance criteria:

- `harness validate` runs all validators.
- CI can run validators on the scaffold repo and target repo.
- Validator errors are readable by humans and agents.

### Phase 7 — Example projects and smoke tests

Goal: prove the scaffold works end-to-end.

Examples:

1. `examples/tiny-cli`
   - simple command-line project;
   - clear test command;
   - no UI.
2. `examples/tiny-webapp`
   - simple web app;
   - screenshot/video proof-of-work pattern;
   - smoke test.

Default tests must not require external credentials. Live tests should be opt-in and clearly marked.

### Phase 8 — Hardening and operations

Goal: make the scaffold safer for repeated use.

Add:

- workspace cleanup guide;
- secret handling guide;
- optional local `.envrc.example`;
- dashboard runbook;
- logs runbook;
- failure modes guide;
- upgrade guide for SPEC compatibility.

---

## 7. Profiles

### `toy-example`

- local workspace root under `.harness/workspaces`;
- concurrency 1;
- fake or placeholder tracker config;
- safe defaults;
- no external credentials required for validation.

### `cautious-linear`

- Linear tracker;
- concurrency 1–3;
- conservative Codex approval/sandbox;
- explicit human review handoff;
- no auto-merge;
- generated review packet required.

### `trusted-local`

- concurrency 4–10;
- workspace-write sandbox;
- optional dashboard;
- can land PRs if CI and review pass;
- still records proof-of-work.

---

## 8. Human operating model

```text
1. Human writes or refines a Linear issue.
2. Issue moves into an active state.
3. Symphony claims the issue and creates a workspace.
4. Codex reads AGENTS.md and docs/.
5. Codex implements, tests, and opens or updates a PR.
6. Codex leaves a review packet.
7. Human reviews the packet and PR.
8. Human accepts, requests rework, or closes as not useful.
9. Useful follow-ups become new issues.
10. Docs are updated when knowledge changed.
```

This is intentionally different from Superteam’s “spec → plan → task directories → reviewer agents” flow. The unit of work is the issue; the agent is trusted to plan internally and use repo-local docs.

---

## 9. Target repo documentation contract

A target repo is considered “agent-ready” when it has:

### Required

- `AGENTS.md`
- `WORKFLOW.md`
- `docs/README.md`
- `docs/PRODUCT.md`
- `docs/ENGINEERING.md`
- `docs/QUALITY.md`
- `docs/RELIABILITY.md`
- `docs/SECURITY.md`
- `ARCHITECTURE.md`
- at least one automated test command
- a clear local bootstrap command

### Recommended

- `docs/design-docs/index.md`
- `docs/exec-plans/active/`
- `docs/exec-plans/completed/`
- `docs/product-specs/index.md`
- `docs/generated/`
- `docs/runbooks/`
- repo-local Codex skills
- CI docs
- PR template

### Optional

- local observability stack;
- UI smoke tests;
- screenshot/video walkthrough tooling;
- docs freshness linter;
- doc-gardening workflow.

---

## 10. How this differs from Superteam

| Dimension | This scaffold | Superteam-style workflow |
|---|---|---|
| Primary unit | Issue/ticket | Spec and planned tasks |
| Orchestration | Symphony runtime | Prompt/state-machine workflow |
| Agent style | Objective-based | Role/state based |
| State source | Issue tracker + repo docs + workspaces | `working/` task files |
| Human interaction | Manage work, review packets | Approve spec/plan, inspect task outputs |
| Reuse target | Project engineering system | Coding workflow inside a repo |
| Scaling | Multiple issues/workspaces | Usually one spec flow at a time |
| Philosophy | Give tools/context and let agent cook | Constrain agent into staged handoffs |

---

## 11. Acceptance criteria for v1

The scaffold reaches v1 when:

1. It implements a hardened SPEC-compatible runtime.
2. It has a functioning `harness init`.
3. It has a functioning `harness validate`.
4. It provides target repo templates:
   - `AGENTS.md`,
   - `WORKFLOW.md`,
   - `docs/`,
   - optional skills/hooks.
5. It has human-facing docs:
   - adoption guide,
   - operating model,
   - issue writing guide,
   - review guide,
   - knowledge base guide,
   - trust and safety guide.
6. It has at least one example project.
7. It has CI that validates the scaffold itself.
8. It documents the Symphony update process.
9. It clearly states the trusted-environment assumption and non-goals.
10. A new project can adopt it in under one hour.

---

# 12. Human-facing documentation to include

The following docs should be committed as part of the scaffold. These are for humans, not agents, although agents may read them too.

---

## 12.1 `docs/README.md`

```markdown
# Harness Engineering Starter: Human Documentation

This repository helps teams make software projects usable by autonomous coding agents.

It is built around three ideas:

1. Work is managed through issues.
2. Agents need a legible repository, not a giant prompt.
3. Humans review outcomes and improve the harness when agents fail.

This repo implements a hardened SPEC-compatible runtime and provides the missing project-engineering layer around it: templates, docs, validation, examples, and operating practices.

## Start here

- New project adoption: `docs/adoption-guide.md`
- Day-to-day operating model: `docs/operating-model.md`
- How to write agent-ready issues: `docs/issue-writing-guide.md`
- How to review agent work: `docs/review-guide.md`
- How to maintain repo knowledge: `docs/knowledge-base-guide.md`
- Safety and trust posture: `docs/trust-and-safety.md`
- Maintaining this scaffold: `docs/maintaining-this-scaffold.md`

## Mental model

The hardened runtime runs agents. This scaffold teaches your repository and your team how to work with those agents.

A successful adoption means:

- a product manager can file an issue that an agent can act on,
- an engineer can review the resulting PR without reconstructing context,
- the repo contains the knowledge the agent needs,
- repeated failures become improvements to docs, tests, tools, or workflow.
```

---

## 12.2 `docs/adoption-guide.md`

```markdown
# Adoption Guide

This guide explains how to adopt the harness scaffold in an existing project.

## 1. Prerequisites

You need:

- a Git repository,
- a working local setup command,
- at least one automated test command,
- Codex installed and authenticated,
- the hardened runtime available through this scaffold,
- a Linear project or another supported issue tracker,
- a trusted environment for running coding agents.

## 2. Initialize the project

From the scaffold repository:

```bash
harness init --target /path/to/your/repo --profile cautious-linear
```

Then inspect the generated files before committing them.

## 3. Fill project-specific placeholders

Edit:

- `AGENTS.md`
- `WORKFLOW.md`
- `ARCHITECTURE.md`
- `docs/PRODUCT.md`
- `docs/ENGINEERING.md`
- `docs/QUALITY.md`
- `docs/RELIABILITY.md`
- `docs/SECURITY.md`
- `docs/OPERATING_MODEL.md`

Do not leave placeholder text in committed docs.

## 4. Configure environment variables

```bash
export LINEAR_API_KEY=...
export LINEAR_PROJECT_SLUG=...
export SOURCE_REPO_URL=git@github.com:your-org/your-repo.git
export SYMPHONY_WORKSPACE_ROOT=~/code/symphony-workspaces/your-repo
```

Do not commit secrets.

## 5. Validate the repo

```bash
harness validate --target /path/to/your/repo
```

Fix all errors before running Symphony.

## 6. Configure Linear states

Recommended initial states:

- `Todo`: work may be picked up.
- `In Progress`: agent or human is working.
- `Rework`: agent should address feedback.
- `Human Review`: agent has produced a review packet.
- `Merging`: ready to land.
- `Done`: terminal.
- `Cancelled`: terminal.
- `Duplicate`: terminal.

You may rename these, but keep the meaning clear in `docs/OPERATING_MODEL.md` and `WORKFLOW.md`.

## 7. Run Symphony

```bash
harness run --workflow /path/to/your/repo/WORKFLOW.md
```

## 8. First smoke test

Create a low-risk issue:

```text
Update docs/README.md to add one sentence explaining the local development command.
```

Move it to an active state and confirm that Symphony creates a workspace, starts Codex, produces a PR or patch, leaves a review packet, and comments or moves the issue according to your workflow.
```

---

## 12.3 `docs/operating-model.md`

```markdown
# Operating Model

Humans manage work. Agents execute work. The issue tracker is the control plane.

## Roles

### Product owner

- writes or approves issues,
- clarifies acceptance criteria,
- reviews user-facing behavior,
- accepts or rejects completed work.

### Engineer

- maintains repo harness quality,
- reviews code and architecture,
- improves tests/docs when agents fail,
- handles high-judgment tasks directly.

### Agent

- reads the issue,
- reads `AGENTS.md` and relevant docs,
- makes changes in an isolated workspace,
- runs tests,
- opens or updates a PR,
- leaves proof of work,
- asks for rework or clarification when needed.

## Workflow states

- `Todo`: eligible for agent pickup.
- `In Progress`: agent or human is working.
- `Rework`: previous output needs fixes.
- `Human Review`: agent believes work is ready.
- `Merging`: work is accepted and should be landed.
- `Done`: work is complete.
- `Cancelled` / `Duplicate`: terminal states.

## When to use this system

Good candidates: routine implementation, test additions, bug fixes with reproduction steps, docs updates, bounded refactors, dependency migrations with clear CI signals, UI tweaks with screenshots or design references.

Poor candidates: unresolved product strategy, ambiguous architecture decisions, sensitive security changes, production incident response without human supervision, tasks requiring credentials or external access not available in the workspace.

## Failure policy

When an agent fails, do not only patch the result manually. Ask whether the issue was unclear, repo knowledge was missing, tests were insufficient, setup was fragile, or the workflow prompt was wrong. Repeated failures should improve the harness.
```

---

## 12.4 `docs/issue-writing-guide.md`

```markdown
# Issue Writing Guide

Agents perform best when issues are concrete, bounded, and verifiable.

## Good issue structure

```markdown
## Objective

What should be true when this issue is complete?

## Context

Why does this matter? Link relevant docs, specs, designs, or previous issues.

## Scope

What files, modules, or product areas are likely involved?

## Acceptance criteria

- [ ] Observable behavior 1
- [ ] Observable behavior 2
- [ ] Tests or CI demonstrate the change
- [ ] Documentation updated if behavior changes

## Constraints

What must not change?

## Proof of work

What should the agent provide for human review?

## Out of scope

What should the agent avoid?
```

## Good example

```text
Add a CLI flag `--json` to the `report` command.

Acceptance:
- `tool report --json` prints valid JSON.
- existing text output remains unchanged without the flag.
- tests cover both output modes.
- docs/CLI.md is updated.
```

## Weak example

```text
Improve report output.
```

The weak version does not specify behavior, tests, or review criteria.
```

---

## 12.5 `docs/review-guide.md`

```markdown
# Review Guide

A ready-for-review issue should include:

- issue identifier,
- PR link,
- summary of changes,
- changed files,
- tests run,
- CI status,
- screenshots/video if UI changed,
- logs/metrics if reliability changed,
- known risks,
- follow-up issues.

## Review checklist

### Problem fit

- Does the change solve the issue?
- Did the agent change the intended area?
- Did it avoid out-of-scope work?

### Correctness

- Are edge cases handled?
- Are tests meaningful?
- Did CI pass?

### Maintainability

- Does the code follow existing patterns?
- Did the agent introduce unnecessary abstractions?
- Are docs updated?

### Safety

- Were secrets touched?
- Were permissions changed?
- Were migrations or destructive operations introduced?

## Outcomes

Accept, request rework with concrete feedback, or close/cancel with a written reason.
```

---

## 12.6 `docs/knowledge-base-guide.md`

```markdown
# Knowledge Base Guide

The repository is the knowledge system of record for agents.

## Recommended structure

```text
docs/
  README.md
  PRODUCT.md
  ENGINEERING.md
  QUALITY.md
  RELIABILITY.md
  SECURITY.md
  OPERATING_MODEL.md
  design-docs/
  exec-plans/
    active/
    completed/
    tech-debt-tracker.md
  product-specs/
  generated/
  runbooks/
```

## Design docs

Each design doc should include problem, decision, alternatives considered, tradeoffs, status, owner, and last verified date.

## Execution plans

Use execution plans for complex multi-step work. Include goal, stages, progress log, decision log, validation steps, and rollback notes.

## Generated docs

Use `docs/generated/` for machine-generated references such as database schema, API schema, route map, dependency graph, and feature flag inventory. Generated docs should say how to regenerate them.

## Doc gardening

Periodically remove stale docs, verify links, update generated references, archive completed plans, and convert repeated review feedback into docs or tests.
```

---

## 12.7 `docs/trust-and-safety.md`

```markdown
# Trust and Safety

This scaffold is intended for trusted engineering environments unless hardened.

## Threat model

Agent runs may read and edit repository files, run shell commands inside workspaces, open PRs, comment on issues, inspect CI logs, and use credentials available in the environment.

## Rules

- Never commit secrets.
- Prefer short-lived credentials.
- Use least-privilege tokens.
- Keep workspace roots separate from important local directories.
- Do not mount production credentials into agent workspaces.
- Do not allow agents to run against production systems without explicit approval.
- Require human review before merge until the project has strong quality gates.

## Recommended defaults

For initial adoption: low concurrency, workspace-write sandbox, no auto-merge, human review handoff, explicit review packet, no production access.

## Incident response

If an agent does something unsafe: stop the runtime, revoke exposed credentials if any, inspect workspace and logs, close or revert PRs, document the failure, and add guardrails before restarting.
```

---

## 12.8 `docs/maintaining-this-scaffold.md`

```markdown
# Maintaining This Scaffold

The scaffold maintainers own templates, docs, validators, examples, SPEC compatibility, upgrade notes, and release notes. They do not own project-specific business logic copied into target repos.

## Updating The Runtime Against The Spec

```bash
make validate
make test
make stale-design-check
```

Update compatibility notes and changelog before release.

## Compatibility policy

- Patch releases should not break generated target repos.
- Minor releases may add templates or validators.
- Major releases may change adoption layout.

## What belongs here

Good additions: reusable docs, issue templates, review packet formats, validation scripts, example workflows, safety guidance.

Bad additions: project-specific feature code, organization secrets, one-off prompts, copied Symphony runtime code without a reason.
```

---

## 13. Initial README draft

```markdown
# Harness Engineering Starter

A reusable scaffold for building agent-friendly software projects with Codex and Symphony.

This repository implements a hardened SPEC-compatible runtime and adds the project-engineering layer around it:

- target repo templates,
- `AGENTS.md` and `WORKFLOW.md` conventions,
- repository knowledge-base structure,
- human operating docs,
- issue-writing and review guides,
- validation scripts,
- example projects.

## Philosophy

Humans steer. Agents execute.

The issue tracker is the control plane. The repository is the knowledge system of record. The hardened runtime runs the agents. This scaffold makes projects ready for that operating model.

## Quick start

```bash
git clone <this-repo>
cd harness-engineering-starter
harness init --target /path/to/your/repo --profile cautious-linear
harness validate --target /path/to/your/repo
```

Then configure `/path/to/your/repo/WORKFLOW.md` and run the hardened runtime:

```bash
harness run --workflow /path/to/your/repo/WORKFLOW.md
```

## Documentation

Start with `docs/README.md`.

## Status

Early hardened runtime scaffold. Use least-privilege credentials and human review gates first.
```

---

## 14. Recommended first build prompt for Codex

```text
Build the v1 harness-engineering scaffold described in docs/implementation-plan.md.

Implement the hardened SPEC-compatible runtime in this repository. Do not depend on upstream implementation code. Keep init, validate, and run commands. Create the templates and human-facing docs described in the plan. Add tests for template copying and validation. Keep AGENTS.md short and make docs/ the system of record.
```

---

## 15. References

- OpenAI Symphony announcement: https://openai.com/index/open-source-codex-orchestration-symphony/
- Symphony repository: https://github.com/openai/symphony
- Symphony service specification: https://github.com/openai/symphony/blob/main/SPEC.md
- Symphony reference skills: https://github.com/openai/symphony/tree/main/.codex/skills
- Harness engineering article: https://openai.com/index/harness-engineering/
- Codex skills documentation: https://developers.openai.com/codex/skills
- Codex AGENTS.md documentation: https://developers.openai.com/codex/guides/agents-md
- Codex hooks documentation: https://developers.openai.com/codex/hooks
