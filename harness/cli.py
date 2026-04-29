"""Command-line interface for the harness scaffold."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from .agents_validator import validate_agents
from .docs_validator import validate_docs
from .project_profiles import PROFILES, get_profile
from .templates import REPO_ROOT, copy_templates
from .workflow_validator import validate_workflow


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="harness", description="Harness engineering scaffold tooling.")
    subcommands = parser.add_subparsers(dest="command", required=True)

    init_parser = subcommands.add_parser("init", help="copy scaffold templates into a target repository")
    init_parser.add_argument("--target", required=True, type=Path)
    init_parser.add_argument("--profile", choices=sorted(PROFILES), default="cautious-linear")
    init_parser.add_argument("--dry-run", action="store_true")
    init_parser.add_argument("--force", action="store_true")
    init_parser.set_defaults(func=cmd_init)

    validate_parser = subcommands.add_parser("validate", help="validate a target repository harness contract")
    validate_parser.add_argument("--target", required=True, type=Path)
    validate_parser.set_defaults(func=cmd_validate)

    run_parser = subcommands.add_parser("run", help="run Symphony with a workflow file")
    run_parser.add_argument("--workflow", required=True, type=Path)
    run_parser.set_defaults(func=cmd_run)

    sync_parser = subcommands.add_parser("sync-symphony", help="initialize or update the Symphony submodule")
    sync_parser.set_defaults(func=cmd_sync_symphony)
    return parser


def cmd_init(args: argparse.Namespace) -> int:
    profile = get_profile(args.profile)
    try:
        operations = copy_templates(args.target.resolve(), profile, dry_run=args.dry_run, force=args.force)
    except FileExistsError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    verb = "would write" if args.dry_run else "wrote"
    for operation in operations:
        print(f"{verb}: {operation.destination}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    target = args.target.resolve()
    messages = []
    messages.extend(validate_docs(target))
    messages.extend(validate_agents(target))
    messages.extend(validate_workflow(target))

    for message in messages:
        print(message.format(target))

    errors = [message for message in messages if message.level == "ERROR"]
    if errors:
        print(f"validation failed with {len(errors)} error(s)", file=sys.stderr)
        return 1
    print("validation passed")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    workflow = args.workflow.resolve()
    if not workflow.is_file():
        print(f"workflow file not found: {workflow}", file=sys.stderr)
        return 2

    symphony_dir = REPO_ROOT / "vendor" / "symphony"
    if not symphony_dir.exists() or not any(symphony_dir.iterdir()):
        print(
            "Symphony submodule is not initialized. Run: git submodule update --init --recursive vendor/symphony",
            file=sys.stderr,
        )
        return 2

    candidates = [
        symphony_dir / "elixir",
        symphony_dir,
    ]
    for cwd in candidates:
        if (cwd / "mix.exs").exists():
            return subprocess.call(["mix", "run", "--", "--workflow", str(workflow)], cwd=cwd)

    print(
        f"Could not find a known Symphony entrypoint under {symphony_dir}. "
        "Open vendor/symphony/SPEC.md for current runtime instructions.",
        file=sys.stderr,
    )
    return 2


def cmd_sync_symphony(args: argparse.Namespace) -> int:
    del args
    return subprocess.call(["git", "submodule", "update", "--init", "--recursive", "vendor/symphony"], cwd=REPO_ROOT)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
