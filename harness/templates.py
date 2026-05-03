"""Template discovery, rendering, and copying."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Protocol

from .project_profiles import ProjectProfile


REPO_ROOT = Path(__file__).resolve().parent.parent


class TemplateResource(Protocol):
    name: str

    def is_file(self) -> bool: ...

    def is_dir(self) -> bool: ...

    def iterdir(self): ...

    def read_text(self, encoding: str = "utf-8") -> str: ...


TEMPLATE_ROOT = resources.files("harness").joinpath("template_data", "repo")


@dataclass(frozen=True)
class TemplateOperation:
    source: TemplateResource
    relative_path: Path
    destination: Path
    action: str


def iter_template_files(template_root: TemplateResource = TEMPLATE_ROOT) -> list[TemplateResource]:
    return sorted(_walk_template_files(template_root), key=lambda path: _relative_to_template_root(path, template_root).as_posix())


def _walk_template_files(root: TemplateResource) -> list[TemplateResource]:
    if isinstance(root, Path):
        return [path for path in root.rglob("*") if _is_template_file(path)]
    files: list[TemplateResource] = []
    for child in root.iterdir():
        if child.name == "__pycache__":
            continue
        if child.is_file() and child.name.endswith(".pyc"):
            continue
        if child.is_file():
            files.append(child)
        elif child.is_dir():
            files.extend(_walk_template_files(child))
    return files


def _is_template_file(path: Path) -> bool:
    return path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"


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


def plan_copy(target: Path, template_root: TemplateResource = TEMPLATE_ROOT) -> list[TemplateOperation]:
    operations: list[TemplateOperation] = []
    for source in iter_template_files(template_root):
        relative = _relative_to_template_root(source, template_root)
        destination = target / relative
        action = "overwrite" if destination.exists() else "create"
        operations.append(TemplateOperation(source, relative, destination, action))
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
        if isinstance(operation.source, Path):
            shutil.copymode(operation.source, operation.destination)
    return operations


def _relative_to_template_root(source: TemplateResource, template_root: TemplateResource) -> Path:
    if isinstance(source, Path) and isinstance(template_root, Path):
        return source.relative_to(template_root)
    parts: list[str] = [source.name]
    current = source
    while True:
        parent = getattr(current, "parent", None)
        if parent is None or parent == template_root:
            break
        parts.append(parent.name)
        current = parent
    return Path(*reversed(parts))
