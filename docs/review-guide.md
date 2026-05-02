# Review Guide

A ready-for-review issue should include issue identifier, PR link, summary of changes, changed files, tests run, CI status, screenshots or video for UI changes, known risks, and follow-up issues.

Use the target repo's `docs/review-packet-template.md` for the Markdown artifact. If a sibling JSON packet is included, validate it locally with:

```sh
python -m harness.cli validate-review-packet --path <review-packet.md>
```

## Checklist

- Problem fit: solves the issue and avoids out-of-scope work.
- Correctness: handles edge cases and has meaningful tests.
- Maintainability: follows existing patterns and avoids unnecessary abstractions.
- Safety: does not expose secrets, widen permissions, or hide destructive operations.

## Outcomes

Accept, request rework with concrete feedback, or close/cancel with a written reason.
