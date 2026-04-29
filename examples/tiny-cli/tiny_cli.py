"""Tiny CLI used by scaffold smoke tests."""

from __future__ import annotations

import argparse


def greet(name: str) -> str:
    return f"hello, {name}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("name", nargs="?", default="agent")
    args = parser.parse_args()
    print(greet(args.name))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
