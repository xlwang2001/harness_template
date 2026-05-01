# Trust and Safety

This scaffold includes hardened runtime defaults, but still requires a deliberately trusted engineering environment.

Agent runs may read and edit repository files, run shell commands inside workspaces, open PRs, comment on issues, inspect CI logs, and use credentials available in the environment.

## Rules

- Never commit secrets.
- Prefer short-lived credentials.
- Use least-privilege tokens.
- Keep workspace roots separate from important local directories.
- Do not mount production credentials into agent workspaces.
- Require human review before merge until the project has strong quality gates.
- Treat Codex app-server user-input-required events as run failures; the runtime must not wait indefinitely for operator input inside an agent session.

## Incident Response

If an agent does something unsafe: stop the runtime, revoke exposed credentials if any, inspect workspace and logs, close or revert PRs, document the failure, and add guardrails before restarting.
