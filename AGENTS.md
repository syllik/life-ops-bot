# AGENTS.md

## Purpose

This public MIT project is a self-hosted Telegram interface for one user and one explicitly configured GitHub repository. The runtime uses only the configured repository and does not require access to any maintainer-owned repository.

## Architecture invariants

- GitHub Issues in the configured repository are the only durable application state.
- Do not add a database, GitHub Project, queue, or other external durable state store without a concrete requirement that cannot be met with GitHub Issues.
- The bot should be restart-safe and reconstruct durable state from GitHub.
- Telegram is an interface, not the authority; use long polling without a public inbound endpoint.
- One deployment authorizes one exact numeric Telegram user ID and targets one configured repository.
- Open Issue = active; closed Issue = done.
- The current behavior requires only `state:inbox` and `state:later`. Treat the `state:*` namespace as bot-managed state semantics. `Later` removes conflicting `state:*` labels, sets exactly `state:later`, reopens the Issue, and preserves unrelated labels.
- Other labels are optional. Do not make area, type, reminder, or other taxonomy labels part of the required repository contract.
- Preserve the original Telegram input and the existing best-effort source-key deduplication behavior.
- Keep bot-owned machine metadata in the Issue body; it must not depend on the repository name.
- Reject unauthorized updates before private message-body processing, GitHub access, or any other external side effect.
- Never log or commit tokens, secrets, recovery codes, private keys, or private user content unnecessarily.

## Startup repository contract

- Validate the configured repository and confirm Issues are enabled before Telegram polling starts.
- Create a missing required state label through the GitHub Issues labels API.
- When all required labels already exist, confirm Issues write access through a semantics-preserving update that retains the existing label value.
- Fail closed on repository access, Issues compatibility, label bootstrap, or Issues-write failures. Keep GitHub response bodies and credentials out of errors.
- Do not use Contents or Admin permissions, write repository files, or introduce repository-level schema/sentinel files for the current contract.

## Testing policy

- Every behavior added to the project must be covered by automated tests in the same change.
- Cover happy paths, failure paths, authorization boundaries, fallbacks, mapping logic, and state-changing actions.
- External systems must be exercised through adapters/fakes in unit tests so tests are deterministic and do not require real Telegram or GitHub credentials.
- Add integration tests around adapter contracts where practical.
- A change is not complete while meaningful behavior introduced by it remains untested.
- Avoid tests that merely mirror implementation details; test observable behavior and invariants.

## Current behavior and future direction

The current vertical slice is:

```text
Telegram text/link/forward
  -> authorize exact sender
  -> preserve original input
  -> create an open GitHub Issue with state:inbox
  -> reply with Saved + Done / Later / GitHub actions
```

The core domain should not depend directly on Telegram or GitHub authentication mechanics. Keep GitHub access behind the existing adapter boundary. Future classifier or reminder behavior may use optional labels and bot-owned Issue body metadata, but those features and their taxonomies are not required now.

## License

MIT.
