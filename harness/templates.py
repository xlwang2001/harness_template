"""Template discovery, rendering, and copying."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from .project_profiles import ProjectProfile


REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_ROOT = REPO_ROOT / "templates" / "repo"


@dataclass(frozen=True)
class TemplateOperation:
    source: Path
    destination: Path
    action: str


def iter_template_files(template_root: Path = TEMPLATE_ROOT) -> list[Path]:
    return sorted(path for path in template_root.rglob("*") if path.is_file())


def render_template(text: str, profile: ProjectProfile) -> str:
    replacements = {
        "{{ profile.name }}": profile.name,
        "{{ profile.tracker_kind }}": profile.tracker_kind,
        "{{ profile.workspace_root }}": profile.workspace_root,
        "{{ profile.max_concurrent_agents }}": str(profile.max_concurrent_agents),
        "{{ profile.max_turns }}": str(profile.max_turns),
        "{{ profile.human_review_state }}": profile.human_review_state,
        "{{ profile.notes }}": profile.notes,
        "{{ profile.active_states_yaml }}": "\n".join(f"    - {state}" for state in profile.active_states),
        "{{ profile.terminal_states_yaml }}": "\n".join(f"    - {state}" for state in profile.terminal_states),
    }
    for needle, value in replacements.items():
        text = text.replace(needle, value)
    return text


def plan_copy(target: Path, template_root: Path = TEMPLATE_ROOT) -> list[TemplateOperation]:
    operations: list[TemplateOperation] = []
    for source in iter_template_files(template_root):
        relative = source.relative_to(template_root)
        destination = target / relative
        action = "overwrite" if destination.exists() else "create"
        operations.append(TemplateOperation(source, destination, action))
    return operations


def copy_templates(target: Path, profile: ProjectProfile, *, dry_run: bool = False, force: bool = False) -> list[TemplateOperation]:
    operations = plan_copy(target)
    conflicts = [op.destination for op in operations if op.destination.exists() and not force]
    if conflicts:
        formatted = "\n".join(f"- {path}" for path in conflicts[:20])
        extra = "" if len(conflicts) <= 20 else f"\n... and {len(conflicts) - 20} more"
        raise FileExistsError(f"refusing to overwrite existing files without --force:\n{formatted}{extra}")

    if dry_run:
        return operations

    target.mkdir(parents=True, exist_ok=True)
    for operation in operations:
        operation.destination.parent.mkdir(parents=True, exist_ok=True)
        text = operation.source.read_text(encoding="utf-8")
        operation.destination.write_text(render_template(text, profile), encoding="utf-8")
        shutil.copymode(operation.source, operation.destination)
    return operations
