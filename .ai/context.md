# Life Ops Bot context

## Product

`life-ops-bot` is a public MIT Telegram client for a self-hosted single-user workflow. Each deployment uses one exact numeric Telegram user ID and one explicitly configured GitHub repository. That repository's GitHub Issues are the only durable application state; the public runtime does not require access to a maintainer-owned repository.

## Goal

Make capture and simple state changes available from Telegram while keeping GitHub Issues as the durable authority and preserving the user's original input.

## MVP architecture

```text
Telegram Bot API (long polling)
          |
          v
authorization by exact numeric user ID
          |
          v
capture original text/link/forward
          |
          v
GitHub adapter
          |
          v
the explicitly configured repository's Issues
```

No public HTTP endpoint, GitHub Project, database, queue, or separate durable application store is part of the current architecture.

## Repository contract

The configured repository must be accessible to the configured credential and have GitHub Issues enabled. The only labels required by current behavior are:

- `state:inbox` — applied to newly captured Issues.
- `state:later` — applied by the Later action.

Treat the `state:*` namespace as bot-managed state semantics. Later reopens the Issue, replaces conflicting `state:*` labels with exactly `state:later`, and preserves unrelated labels. Open Issues are active; closed Issues are done. Other labels are optional and are not part of the required repository taxonomy.

At startup, validate repository access and Issues support, create either required label if missing, and verify Issues write capability before starting Telegram polling. When the required labels already exist, use a semantics-preserving update that retains the existing value. Fail closed if any contract check fails.

The Issue body keeps original Telegram input, source identifiers, and the bot-owned hidden metadata (`schema: 1`). This metadata contract belongs to the application; it does not assert anything about the target repository name. Capture deduplication by Telegram chat/message source key remains best-effort.

## Current Telegram behavior

Accepted input: text, links, and forwarded Telegram messages. The current capture uses a deterministic title, stores the original input, applies `state:inbox`, and offers Done, Later, and GitHub actions. Done closes the Issue.

Unauthorized senders must be rejected before reading the private message body or causing external side effects.

## Configuration and credentials

Required runtime values:

- `TELEGRAM_BOT_TOKEN` — secret.
- `TELEGRAM_ALLOWED_USER_ID` — exact positive numeric user ID.
- `GITHUB_TOKEN` — secret.
- `GITHUB_REPOSITORY` — required `owner/repository` configuration.

For local/self-hosted first run, the application reads an optional untracked `.env` file. Process environment variables override `.env`, so deployment platforms can inject the same values without changing application behavior. Secret interpolation from the local file is disabled.

The recommended current GitHub credential is a fine-grained personal access token scoped to the selected repository with Issues read and write access. GitHub App authentication can be considered later for more scalable or long-lived installations; it is not implemented now. Do not commit real values.

## Testing

Every functional change must include deterministic tests for observable behavior, authorization/privacy boundaries, external-service failures, GitHub mapping and mutations, Telegram callbacks, and state transitions. Use fakes or mock transports; do not require production credentials or live network access.

## Future direction

Classifier and reminder capabilities are later work. They may use optional labels and bot-owned Issue body metadata, but they must not expand the current required label contract. Navigation, search, multi-user support, public endpoints, and deployment packaging are outside the current slice.

Keep the domain independent of Telegram and GitHub authentication mechanics. Use the existing GitHub Issues adapter as the boundary for repository access.
