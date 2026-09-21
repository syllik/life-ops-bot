# life-ops-bot

A small, public MIT Telegram interface for one self-hosted user and one explicitly configured GitHub repository. Each deployment authorizes one exact numeric Telegram user and uses that repository's GitHub Issues as its only durable application state. The runtime does not depend on access to any maintainer-owned repository.

## Current behavior and repository contract

```text
Telegram text / link / forward
    -> exact numeric user authorization
    -> preserve original input
    -> create an open GitHub Issue with state:inbox
    -> reply with Saved + Done / Later / GitHub actions
```

Open Issues are active and closed Issues are done. The bot-managed state labels required by the current behavior are `state:inbox` and `state:later`. Startup checks that the configured repository is accessible and Issues are enabled, then creates either required label if missing. If both labels already exist, startup performs a semantics-preserving update with the existing color to verify Issues write access. Any failed check stops startup before Telegram polling.

`Later` reopens the Issue, removes conflicting labels in the `state:*` namespace, and sets exactly `state:later`. It preserves unrelated labels. Other labels are optional and are not required for the current bot behavior. Captures use a deterministic title and preserve the original Telegram input in the Issue body.

Capture writes use `(telegram chat_id, message_id)` as a stable source key in bot-owned Issue body metadata (`schema: 1`). Before creating an Issue, the bot scans the 100 most recently created Issues for that key. This is best-effort deduplication, not transactional exactly-once delivery: a concurrent race or a retry older than the scan window can still create a duplicate. `Done` and `Later` are idempotent state-setting operations.

The bot uses Telegram long polling. It has no public HTTP endpoint, database, queue, GitHub Project, or other durable state store. GitHub Issues remain the source of truth after process restarts.

## Configuration

Python 3.12+ is required. Provide these environment variables through your deployment's configuration mechanism:

- `TELEGRAM_BOT_TOKEN` — secret bot token.
- `TELEGRAM_ALLOWED_USER_ID` — configuration; the exact positive numeric Telegram user ID allowed to use this deployment.
- `GITHUB_TOKEN` — secret credential for the selected repository.
- `GITHUB_REPOSITORY` — required configuration in `owner/repository` form.

The recommended credential is a fine-grained personal access token scoped only to the selected repository, with **Issues: Read and write** permission. The current contract uses GitHub Issues and labels APIs; it does not need Contents or Admin permissions. Startup verifies the configured access before polling. Keep real secrets outside Git. The application does not load `.env` files itself.

GitHub App authentication may be a later option for more scalable or long-lived installations. It is not implemented in the current version.

Install and run:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
life-ops-bot
```

Validation:

```bash
pytest
ruff check .
```

## Architecture boundaries

Unauthorized Telegram users are rejected before private message text is read, GitHub is called, or a Telegram response is sent. GitHub errors returned to Telegram are sanitized and never include private response bodies. Core behavior is independent of Telegram and GitHub implementations; the current adapters are aiogram 3.x and a small httpx GitHub REST client.

The Issue body metadata is owned by the bot and is independent of the target repository's name or optional label taxonomy. Future classifier or reminder features can use optional labels and bot-owned metadata, but neither feature is part of the current repository contract.

## Deferred intentionally

Not part of the current slice: LLM classification, navigation/search, reminders, deployment/containerization, multi-user support, webhooks, or a public server.

## License

MIT.
