# Runtime Production Readiness Checklist

Use this checklist before running the hardened runtime against a production project, and repeat the relevant parts whenever `SPEC.md`, Codex app-server, Linear behavior, workflow config, or runtime templates change.

## Required Before First Production Use

1. Run the default local checks:

   ```sh
   make test
   make validate
   make stale-design-check
   git diff --check
   ```

2. Run the gated integration profile with explicit credentials:

   ```sh
   HARNESS_RUN_INTEGRATION=1 \
   LINEAR_API_KEY=... \
   LINEAR_PROJECT_SLUG=... \
   HARNESS_INTEGRATION_CODEX_COMMAND="codex app-server" \
   make integration-test
   ```

3. Confirm the integration profile passes against the intended Linear project and Codex command. The Linear checks are read-only. The service-loop smoke uses fakes for dispatch and cleanup so production tracker state is not mutated.
4. Confirm `WORKFLOW.md` uses environment indirection for credentials and validates with `harness run WORKFLOW.md` startup checks before leaving the runtime unattended.
5. Review `docs/runtime/runbooks.md` with the operator who will own workspace cleanup, logs, status API access, and failure response.

## Required During Codex App-Server Upgrades

Run schema verification whenever the installed Codex app-server version changes or `harness/runtime/agent.py` changes protocol envelopes:

```sh
make codex-schema-test
```

If the local Codex command cannot generate schemas, set `HARNESS_CODEX_SCHEMA_DIR` to a reviewed generated schema directory and run:

```sh
python3 -m unittest tests.runtime.test_codex_schema
```

Do not treat a Codex upgrade as production-ready until schema verification and the gated Codex integration smoke both pass.

## Required During Linear Or Workflow Changes

Run the gated Linear integration checks when any of these change:

- Linear project slug, active states, terminal states, labels, or blocker conventions;
- Linear GraphQL response handling in `harness/runtime/tracker.py`;
- the `linear_graphql` client-side tool;
- workflow front matter that affects tracker auth or issue selection.

These checks must remain read-only. If a future production check needs to mutate Linear state, add a separate explicitly named environment gate and document the cleanup procedure before enabling it.

The reserved mutation gate is `HARNESS_RUN_LINEAR_MUTATION_INTEGRATION=1`. Do not use it until the target issue, target state, comment body, cleanup procedure, and rollback expectations are documented for the project. The default integration profile must stay read-only.

## Release Checklist For Scaffold Maintainers

Before tagging or publishing a scaffold runtime release:

1. Run the default local checks.
2. Run `make integration-test` with `HARNESS_RUN_INTEGRATION=1` and the release-target Linear/Codex profile.
3. Run `make codex-schema-test` if Codex app-server, `CodexAgentRunner`, or schema fixtures changed.
4. Update `docs/runtime/spec-conformance-matrix.md` and `docs/runtime/spec-conformance-todo.md`.
5. Call out integration and schema verification status in release notes.
