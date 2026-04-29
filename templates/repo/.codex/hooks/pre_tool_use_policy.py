#!/usr/bin/env python3
"""Example pre-tool policy hook.

Customize this file in the target repo before enforcing it.
"""

import json
import sys


def main() -> int:
    event = json.load(sys.stdin)
    command = " ".join(event.get("command", []))
    if "production" in command.lower():
        print("Production access requires explicit human approval.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
