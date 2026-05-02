"""Read-only dispatch preview support."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .models import Issue, RuntimeConfig
from .prompt import TemplateRenderError, render_prompt
from .tracker import LinearClient
from .workflow import load_workflow, resolve_config, validate_dispatch_config
from .workspace import WorkspaceManager


@dataclass(frozen=True)
class CandidatePreview:
    issue: Issue
    eligible: bool
    reason: str
    workspace_path: Path
    prompt_preview: str | None
    prompt_error: str | None


@dataclass(frozen=True)
class DispatchPreview:
    workflow_path: Path
    config: RuntimeConfig
    candidates: list[CandidatePreview]

    @property
    def has_errors(self) -> bool:
        return any(candidate.prompt_error for candidate in self.candidates)


def build_dispatch_preview(workflow_path: Path, *, limit: int = 10) -> DispatchPreview:
    workflow = load_workflow(workflow_path)
    config = resolve_config(workflow)
    validate_dispatch_config(config)
    tracker = LinearClient(config)
    candidates = tracker.fetch_candidate_issues()
    return compute_dispatch_preview(config, workflow.prompt_template, candidates, limit=limit)


def compute_dispatch_preview(config: RuntimeConfig, prompt_template: str, candidates: list[Issue], *, limit: int = 10) -> DispatchPreview:
    workspace_manager = WorkspaceManager(config)
    sorted_candidates = _sort_for_dispatch(candidates)[:limit]
    previews: list[CandidatePreview] = []
    planned_global = 0
    planned_by_state: dict[str, int] = {}
    for issue in sorted_candidates:
        eligible, reason = _eligibility_reason(config, issue, planned_global, planned_by_state)
        prompt_preview = None
        prompt_error = None
        if eligible:
            try:
                prompt_preview = _truncate(render_prompt(prompt_template, issue, attempt=None))
            except TemplateRenderError as exc:
                prompt_error = str(exc)
                eligible = False
                reason = "prompt_render_failed"
        if eligible:
            planned_global += 1
            state_key = issue.normalized_state
            planned_by_state[state_key] = planned_by_state.get(state_key, 0) + 1
        previews.append(
            CandidatePreview(
                issue=issue,
                eligible=eligible,
                reason=reason,
                workspace_path=workspace_manager.path_for_issue(issue.identifier),
                prompt_preview=prompt_preview,
                prompt_error=prompt_error,
            )
        )
    return DispatchPreview(workflow_path=config.workflow_path, config=config, candidates=previews)


def format_dispatch_preview(preview: DispatchPreview) -> str:
    lines = [
        f"Dispatch preview for {preview.workflow_path}",
        "",
        "Config:",
        f"- tracker: {preview.config.tracker_kind}",
        f"- project_slug: {preview.config.tracker_project_slug}",
        f"- active_states: {', '.join(preview.config.active_states)}",
        f"- terminal_states: {', '.join(preview.config.terminal_states)}",
        f"- max_concurrent_agents: {preview.config.max_concurrent_agents}",
        f"- workspace_root: {preview.config.workspace_root}",
        "",
        "Candidates:",
    ]
    if not preview.candidates:
        lines.append("- none")
        return "\n".join(lines)
    for index, candidate in enumerate(preview.candidates, start=1):
        issue = candidate.issue
        lines.extend(
            [
                f"{index}. {issue.identifier} - {issue.title}",
                f"   state: {issue.state}",
                f"   priority: {issue.priority if issue.priority is not None else 'none'}",
                f"   eligible: {'yes' if candidate.eligible else 'no'}",
                f"   reason: {candidate.reason}",
                f"   workspace: {candidate.workspace_path}",
            ]
        )
        if candidate.prompt_error:
            lines.append(f"   prompt: render failed: {candidate.prompt_error}")
        elif candidate.prompt_preview is not None:
            lines.append(f"   prompt: {candidate.prompt_preview}")
    return "\n".join(lines)


def _eligibility_reason(config: RuntimeConfig, issue: Issue, planned_global: int, planned_by_state: dict[str, int]) -> tuple[bool, str]:
    if not issue.id:
        return False, "missing_id"
    if not issue.identifier:
        return False, "missing_identifier"
    if not issue.title:
        return False, "missing_title"
    if not issue.state:
        return False, "missing_state"
    if config.is_terminal_state(issue.state):
        return False, "terminal_state"
    if not config.is_active_state(issue.state):
        return False, "inactive_state"
    if issue.normalized_state == "todo":
        for blocker in issue.blocked_by:
            if not config.is_terminal_state(blocker.state):
                label = blocker.identifier or blocker.id or "unknown"
                return False, f"blocked_by non-terminal issue {label}"
    if planned_global >= config.max_concurrent_agents:
        return False, "global_concurrency_exhausted"
    state_key = issue.normalized_state
    state_limit = config.max_concurrent_agents_by_state.get(state_key, config.max_concurrent_agents)
    if planned_by_state.get(state_key, 0) >= state_limit:
        return False, "state_concurrency_exhausted"
    return True, "eligible"


def _sort_for_dispatch(issues: list[Issue]) -> list[Issue]:
    return sorted(
        issues,
        key=lambda issue: (
            issue.priority if issue.priority is not None else 999999,
            issue.created_at or datetime.max.replace(tzinfo=timezone.utc),
            issue.identifier,
        ),
    )


def _truncate(text: str, limit: int = 300) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 3]}..."
