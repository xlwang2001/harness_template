# 0003 Avoid Rigid Superteam Style State Machines

## Status

Accepted

## Decision

The scaffold uses issue-centric Symphony orchestration and objective-based Codex execution rather than a rigid planner, implementer, reviewer state machine.

## Rationale

The unit of work is the issue. The agent should receive objective, context, tools, and quality gates, then plan internally while producing reviewable evidence.
