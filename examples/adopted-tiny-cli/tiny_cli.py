"""Tiny CLI used by the adopted harness example."""

from __future__ import annotations

import argparse
import json


def report(*, json_output: bool = False) -> str:
    payload = {"name": "tiny-cli", "status": "ok"}
    if json_output:
        return json.dumps(payload, sort_keys=True)
    return "tiny-cli status: ok"


def main() -> int:
    parser = argparse.ArgumentParser()
    subcommands = parser.add_subparsers(dest="command")
    report_parser = subcommands.add_parser("report")
    report_parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.command == "report":
        print(report(json_output=args.json))
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
