# Review Packet

Use this skill before handing work to a human.

Create or update a review packet using `docs/review-packet-template.md`. Markdown is sufficient for human review. Add a sibling `.json` packet when CI or local validation should machine-check the proof of work.

Run:

```sh
python -m harness.cli validate-review-packet --path docs/exec-plans/completed/<issue-id>/review-packet.md
```

Include:

- issue identifier,
- pull request link,
- summary of intent,
- changed files,
- tests run,
- CI status,
- screenshots or video if UI changed,
- logs or metrics if reliability changed,
- known risks,
- review checklist,
- follow-up issues created.
