# AGENTS.md

## Purpose

This repository contains the public Telegram client for the private `syllik/life-ops` GitHub Issues store.

## Architecture invariants

- GitHub Issues in `syllik/life-ops` are the durable source of truth.
- Do not add SQLite, another database, a GitHub Project, a queue, or an external durable state store unless a concrete requirement cannot be satisfied with GitHub Issues.
- The bot should be restart-safe and reconstruct durable state from GitHub.
- Telegram is an interface, not the authority.
- Open Issue = active; closed Issue = done.
- Use existing `area:*`, `type:*`, and sparse `state:*` labels.
- Preserve the original Telegram text when generating normalized titles/summaries.
- If semantic classification fails, save safely to Inbox rather than losing the input.
- Location/geofencing is out of scope.
- Single-user first. Reject any sender whose numeric Telegram user ID does not exactly match the configured allowlist.
- Reject unauthorized updates before LLM calls, GitHub writes, logs containing message bodies, or any other processing.
- Never log or commit tokens, secrets, recovery codes, private keys, or private Life Ops content unnecessarily.

## Testing policy

- Every behavior added to the project must be covered by automated tests in the same change.
- Do not defer tests to a later cleanup phase.
- Cover happy paths, failure paths, authorization boundaries, fallbacks, mapping logic, and state-changing actions.
- External systems must be exercised through adapters/fakes in unit tests so tests are deterministic and do not require real Telegram, GitHub, or LLM credentials.
- Add integration tests around adapter contracts where practical.
- A change is not considered complete while meaningful behavior introduced by that change remains untested.
- Avoid tests that merely mirror implementation details; test observable behavior and invariants.

## MVP boundaries

First vertical slice:

```text
Telegram text/link/forward
  -> authorize sender
  -> semantic classification
  -> create GitHub Issue
  -> reply with Saved + Done / Later / GitHub actions
```

Then add navigation. Reminders come after basic capture/navigation is stable.

## Implementation guidance

- Prefer Telegram Bot API long polling for the initial deployment.
- No inbound public port is required.
- Keep the LLM provider behind a small replaceable interface.
- Keep GitHub access behind a small adapter.
- The core domain should not depend directly on Telegram or a specific LLM provider.
- Do not use a trusted self-hosted runner for untrusted public pull requests.

## Upstream / analogues

Analogue research has already been completed. `nxt-am/tg-bot-reminders` and `mtzanidakis/dodo` are reference material only; do not copy substantial code without re-checking licensing/attribution requirements.

## License

MIT.
