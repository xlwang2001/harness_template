# Review Packet: ABC-123

## Issue

- Identifier: ABC-123
- Title: Add `--json` output to report command
- Link: docs/sample-issues/add-json-output.md

## Pull Request

- Link: local example
- Status: merged in example

## Summary

Added JSON output while preserving text output.

## Changed files

- tiny_cli.py
- tests/test_tiny_cli.py
- README.md

## Tests run

| Command | Result | Notes |
|---|---|---|
| `python -m unittest discover -s tests` | passed | Covers text and JSON output. |

## CI status

Local example only.

## Screenshots or video

Not applicable.

## Logs, metrics, or traces

Not applicable.

## Known risks

No known risks.

## Follow-up issues

No follow-ups.

## Human review checklist

- [x] Solves the issue
- [x] Tests are meaningful
- [x] CI is passing or failures are explained
- [x] Scope is appropriate
- [x] Docs updated where needed
- [x] No secret or unsafe production access introduced
