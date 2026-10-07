# Life Ops Bot context

## Product

`life-ops-bot` is a public MIT Telegram client for a self-hosted single-user workflow. Each deployment uses one exact numeric Telegram user ID and one explicitly configured GitHub repository. That repository's GitHub Issues are the only durable application state; the public runtime does not require access to a maintainer-owned repository.

## Goal

Make capture and simple state changes available from Telegram while keeping GitHub Issues as the durable authority and preserving the user's original input.

## Runtime architecture

Production:

```text
Telegram Bot API
    -> authenticated HTTPS webhook
    -> Vercel-hosted Starlette/ASGI entrypoint
    -> exact numeric user authorization
    -> existing Telegram router/domain logic
    -> GitHub adapter
    -> configured repository Issues
```

The production endpoint is `POST /api/telegram/webhook`. Telegram webhook authentication uses the configured `TELEGRAM_WEBHOOK_SECRET` delivered in `X-Telegram-Bot-Api-Secret-Token`.

Long polling remains available only as a local/development fallback. Telegram webhooks and `getUpdates`/polling are mutually exclusive and must not be operated at the same time.

No GitHub Project, database, queue, local filesystem persistence, or separate durable application store is part of the current architecture. Vercel is the reference deployment target, not a dependency of the core domain.

## Repository contract

The configured repository must be accessible to the configured credential and have GitHub Issues enabled. The only labels required by current behavior are:

- `state:inbox` — applied to newly captured Issues.
- `state:later` — applied by the Later action.

Treat the `state:*` namespace as bot-managed state semantics. Later reopens the Issue, replaces conflicting `state:*` labels with exactly `state:later`, and preserves unrelated labels. Open Issues are active; closed Issues are done. Other labels are optional and are not part of the required repository taxonomy.

The runtime validates repository access, Issues support, required labels, and Issues write capability before normal update processing. A webhook process may remember a successful validation for the life of one warm instance, but a cold start must remain correct without that memory. The local polling transport performs the same validation before polling starts. Fail closed if a contract check fails.

The Issue body keeps original Telegram input, source identifiers, and the bot-owned hidden metadata (`schema: 1`). This metadata contract belongs to the application; it does not assert anything about the target repository name. Capture deduplication by Telegram chat/message source key remains best-effort. Webhook setup uses a single Telegram delivery connection to avoid normal concurrent retry races; Done and Later remain idempotent state-setting operations.

## Current Telegram behavior

Accepted capture input: text, links, and forwarded Telegram messages. Capture uses a deterministic title, stores the original input, applies `state:inbox`, and offers Done, Later, and GitHub actions. Done closes the Issue.

Normal navigation is button-driven after the initial `/start` entry point. A persistent native Telegram keyboard exposes Tasks, Goals, Later, and Done. Lists and detail views use inline controls for opening items, returning through context, Done, Later, GitHub, and pagination. Navigation reads current state from GitHub Issues and does not create a separate durable navigation store.

A goal is an Issue that acts as a real parent in the existing hierarchy; no `type:goal` taxonomy is required. Parent/child relations are resolved deterministically from child `Parent: #N` metadata and parent checklist Issue references. Goal detail shows completed and remaining child counts based on child Issue open/closed state.

For production webhooks, reject a missing/incorrect webhook secret before reading the HTTP request body. After authenticated JSON transport parsing, reject unauthorized Telegram senders before aiogram/domain processing or GitHub access.

## Configuration and credentials

Required runtime values:

- `TELEGRAM_BOT_TOKEN` — secret.
- `TELEGRAM_ALLOWED_USER_ID` — exact positive numeric user ID.
- `GITHUB_TOKEN` — secret.
- `GITHUB_REPOSITORY` — required `owner/repository` configuration.

Production webhook additionally requires:

- `TELEGRAM_WEBHOOK_SECRET` — secret accepted by Telegram's `secret_token` contract.

For local/self-hosted first run, the application reads an optional untracked `.env` file. Process environment variables override `.env`, so deployment platforms can inject the same values without changing application behavior. Secret interpolation from the local file is disabled.

The recommended current GitHub credential is a fine-grained personal access token scoped to the selected repository with Issues read and write access. GitHub App authentication can be considered later for more scalable or long-lived installations; it is not implemented now. Do not commit real values.

Webhook registration is an explicit operator action after deployment. The setup helper reads the token and webhook secret from runtime configuration so credentials do not need to appear in shell command history.

## Testing

Every functional change must include deterministic tests for observable behavior, authorization/privacy boundaries, external-service failures, GitHub mapping and mutations, Telegram callbacks, and state transitions. Use fakes or mock transports; do not require production credentials or live network access.

Webhook tests must cover authentication-before-body, unauthorized sender isolation, malformed input, retryable processing failures, callback/message routing, and repository-contract cold-start behavior.

## Future direction

Classifier and reminder capabilities are later work. They may use optional labels and bot-owned Issue body metadata, but they must not expand the current required label contract.

Reminder scheduling is intentionally separate from webhook request handling. Persist reminder state durably in GitHub and use a durable scheduler/trigger when that feature is implemented; do not rely on in-memory timers.

Keep the domain independent of Telegram and GitHub authentication mechanics. Use the existing GitHub Issues adapter as the boundary for repository access.
