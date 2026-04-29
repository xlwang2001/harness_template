"""Project profile defaults used when rendering templates."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProjectProfile:
    name: str
    tracker_kind: str
    workspace_root: str
    max_concurrent_agents: int
    max_turns: int
    active_states: tuple[str, ...]
    terminal_states: tuple[str, ...]
    human_review_state: str
    notes: str


PROFILES: dict[str, ProjectProfile] = {
    "cautious-linear": ProjectProfile(
        name="cautious-linear",
        tracker_kind="linear",
        workspace_root="$SYMPHONY_WORKSPACE_ROOT",
        max_concurrent_agents=2,
        max_turns=20,
        active_states=("Todo", "In Progress", "Rework"),
        terminal_states=("Done", "Closed", "Cancelled", "Canceled", "Duplicate"),
        human_review_state="Human Review",
        notes="Conservative Linear-backed profile with human review handoff and no auto-merge.",
    ),
    "trusted-local": ProjectProfile(
        name="trusted-local",
        tracker_kind="linear",
        workspace_root="$SYMPHONY_WORKSPACE_ROOT",
        max_concurrent_agents=4,
        max_turns=30,
        active_states=("Todo", "In Progress", "Rework"),
        terminal_states=("Done", "Closed", "Cancelled", "Canceled", "Duplicate"),
        human_review_state="Human Review",
        notes="Higher-concurrency trusted local profile for mature repos with strong quality gates.",
    ),
    "toy-example": ProjectProfile(
        name="toy-example",
        tracker_kind="placeholder",
        workspace_root=".harness/workspaces",
        max_concurrent_agents=1,
        max_turns=10,
        active_states=("Todo", "In Progress"),
        terminal_states=("Done", "Cancelled"),
        human_review_state="Human Review",
        notes="Credential-free example profile for local smoke tests and demos.",
    ),
}


def get_profile(name: str) -> ProjectProfile:
    try:
        return PROFILES[name]
    except KeyError as exc:
        allowed = ", ".join(sorted(PROFILES))
        raise ValueError(f"unknown profile {name!r}; expected one of: {allowed}") from exc
