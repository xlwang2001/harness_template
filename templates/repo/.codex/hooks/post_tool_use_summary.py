#!/usr/bin/env python3
"""Example post-tool summary hook."""

import json
import sys


def main() -> int:
    event = json.load(sys.stdin)
    tool = event.get("tool", "unknown")
    status = event.get("status", "unknown")
    print(f"tool={tool} status={status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
