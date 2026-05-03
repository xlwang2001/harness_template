#!/usr/bin/env python3
"""Example stop hook for checking handoff artifacts."""

from pathlib import Path


def main() -> int:
    if not Path("AGENTS.md").exists():
        print("AGENTS.md missing from workspace")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
