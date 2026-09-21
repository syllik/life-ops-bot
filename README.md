# life-ops-bot

Small Telegram interface for a GitHub-hosted personal task and reminder system.

The durable data lives in the private `syllik/life-ops` repository. This public repository contains only the bot code and documentation.

## Current vertical slice

```text
Telegram text / link / forward
    -> exact numeric user authorization
    -> preserve original input
    -> create state:inbox GitHub Issue
    -> reply with Saved + Done / Later / GitHub actions
```

The bot uses Telegram long polling. It has no public HTTP endpoint and no application database.

`Done` closes the Issue. `Later` preserves non-state labels and replaces any conflicting `state:*` label with `state:later`. Until the replaceable classifier is added, every new capture is saved as `state:inbox` with a deterministic title.

## Idempotency

Capture writes use `(telegram chat_id, message_id)` as a stable source key stored in the Issue body. Before creating an Issue, the bot scans the 100 most recently created Issues for that key. This survives normal process restarts and Telegram redelivery without introducing a database.

This is deliberately best-effort rather than transactional exactly-once delivery: a concurrent race between the lookup and create can still duplicate an Issue, and a retry older than the 100-Issue scan window can do the same. The bot is single-user/single-process, so that trade-off is acceptable for the first slice. `Done` and `Later` are idempotent state-setting operations.

## Configuration

Python 3.12+ is required.

Copy `.env.example` into your deployment secret/configuration mechanism and provide:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_ALLOWED_USER_ID` — exact positive numeric Telegram user ID
- `GITHUB_TOKEN` — minimum permissions required to read/write Issues in `syllik/life-ops`
- `LIFE_OPS_REPOSITORY` — defaults to `syllik/life-ops`

The application intentionally does not load `.env` files itself. Keep real secrets outside Git and inject them into the environment.

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

GitHub Issues are the source of truth. The bot does not own SQLite, a GitHub Project, a queue, or another durable state store. Core behavior is independent of Telegram and GitHub implementations; the current adapters are aiogram 3.x and a small httpx GitHub REST client.

Unauthorized Telegram users are rejected before message text is read, GitHub is called, or any Telegram response is sent. GitHub errors returned to Telegram are sanitized and never include private response bodies.

## Deferred intentionally

Not part of this slice: LLM classification, navigation/search, reminders, deployment/containerization, multi-user support, or a webhook/public server.

## Analogue decision

Existing projects were reviewed before starting this tool, including `nxt-am/tg-bot-reminders` and `mtzanidakis/dodo`.

They provide useful reference patterns for Telegram UX, timezone handling, allowlisting, polling/backoff, and operations. They are not used as a fork base because the current Life Ops architecture is GitHub-Issues-first and intentionally avoids their database/scheduler-centric application state.

## License

MIT.
