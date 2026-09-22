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

## First run

Python 3.12+ is required.

Create a virtual environment and install the project:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
chmod 600 .env
```

The local `.env` file is ignored by Git and is the simplest first-run configuration path. Deployment platforms can inject the same names as normal environment variables; process environment variables always override values from `.env`.

Configure these values in `.env`:

- `TELEGRAM_BOT_TOKEN` — secret token created by Telegram's official `@BotFather`.
- `TELEGRAM_ALLOWED_USER_ID` — the exact positive numeric Telegram user ID allowed to use this deployment.
- `GITHUB_TOKEN` — secret GitHub credential for the selected repository.
- `GITHUB_REPOSITORY` — non-secret repository name in `owner/repository` form.

### Telegram setup

1. Open Telegram's official `@BotFather`, create a bot with `/newbot`, and copy the token into `TELEGRAM_BOT_TOKEN`.
2. Send any message to the new bot.
3. With the virtual environment active and the token already saved in `.env`, run the command below. It reads the token locally and prints sender IDs from the bot's recent updates without putting the token in your shell command history:

```bash
python - <<'PY'
from dotenv import dotenv_values
import httpx

token = dotenv_values(".env", interpolate=False)["TELEGRAM_BOT_TOKEN"]
response = httpx.get(
    f"https://api.telegram.org/bot{token}/getUpdates",
    timeout=10,
)
response.raise_for_status()

for update in response.json().get("result", []):
    message = update.get("message") or update.get("edited_message")
    if not message or "from" not in message:
        continue
    sender = message["from"]
    label = sender.get("username") or sender.get("first_name") or ""
    print(sender["id"], label)
PY
```

Copy your numeric ID into `TELEGRAM_ALLOWED_USER_ID`. The runtime authorizes exactly that ID.

### GitHub setup

Create or choose the repository whose Issues will hold the life-ops state. Create a fine-grained personal access token scoped only to that repository with **Issues: Read and write** permission. The current contract does not require Contents or Administration permission.

Put the token in `GITHUB_TOKEN` and the repository name in `GITHUB_REPOSITORY`.

Start the bot:

```bash
life-ops-bot
```

Startup validates repository access, confirms Issues are enabled, bootstraps the required state labels if needed, and verifies Issues write access before Telegram polling starts.

GitHub App authentication may be a later option for more scalable or long-lived installations. It is not implemented in the current version.

## Configuration precedence

The runtime reads an optional local `.env` file and then overlays the process environment. This gives local/self-hosted users a no-`export` first run while keeping container and hosting-provider configuration conventional.

Secrets are:

- `TELEGRAM_BOT_TOKEN`
- `GITHUB_TOKEN`

Non-secret configuration is:

- `TELEGRAM_ALLOWED_USER_ID`
- `GITHUB_REPOSITORY`

Keep real tokens out of Git, logs, examples, screenshots, and support conversations. The application does not write secrets back to disk.

## Validation

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
