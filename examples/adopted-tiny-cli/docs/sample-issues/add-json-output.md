# Example Issue: Add `--json` Output To Report Command

## Objective

`tiny-cli report --json` should print valid JSON while preserving existing text output by default.

## Acceptance Criteria

- `tiny-cli report` keeps existing text output.
- `tiny-cli report --json` prints valid JSON.
- Tests cover both output modes.
- Docs mention the new flag.
- Review packet includes test results.
