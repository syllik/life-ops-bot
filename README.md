# life-ops-bot

A small public MIT Telegram interface for one self-hosted user and one explicitly configured GitHub repository. Each deployment authorizes one exact numeric Telegram user ID and uses that repository's GitHub Issues as its only durable application state.

## Runtime model

Production uses Telegram webhooks:

```text
Telegram
  -> POST /api/telegram/webhook
  -> Vercel / Starlette ASGI app
  -> exact numeric user authorization
  -> existing bot/domain logic
  -> GitHub Issues
  -> Telegram response
```

GitHub Issues remain the source of truth across cold starts and redeploys. There is no application database, queue, local persistence, or always-running process.

Long polling remains available only for local/development use. Telegram webhooks and long polling are mutually exclusive.

## Current behavior

Accepted input: text, links, and forwarded Telegram messages.

```text
Telegram input
    -> authorize exact numeric sender
    -> preserve original input
    -> create/open GitHub Issue with state:inbox
    -> reply with Saved + Done / Later / GitHub actions
```

Open Issues are active and closed Issues are done. The required bot-owned labels are:

- `state:inbox`
- `state:later`

`Later` reopens the Issue, removes conflicting `state:*` labels, sets `state:later`, and preserves unrelated labels.

Capture writes use `(telegram chat_id, message_id)` as a stable source key in bot-owned Issue metadata. The bot scans recent Issues before creating a new one. This makes normal Telegram retry delivery idempotent; the setup helper also registers the webhook with `max_connections=1` to avoid normal concurrent delivery races.

## Requirements

- Python 3.12+
- Telegram bot token from the official `@BotFather`
- exact numeric Telegram user ID allowed to use the deployment
- GitHub repository with Issues enabled
- fine-grained GitHub PAT scoped to that repository with **Issues: Read and write**
- Vercel account for the reference production deployment

## Configuration

Copy the example for local use:

```bash
cp .env.example .env
chmod 600 .env
```

Runtime values:

- `TELEGRAM_BOT_TOKEN` — secret.
- `TELEGRAM_ALLOWED_USER_ID` — exact positive numeric Telegram user ID.
- `GITHUB_TOKEN` — secret fine-grained GitHub PAT.
- `GITHUB_REPOSITORY` — target in `owner/repository` form.
- `TELEGRAM_WEBHOOK_SECRET` — production webhook secret. Telegram accepts 1-256 characters from `A-Z a-z 0-9 _ -`.

`TELEGRAM_WEBHOOK_SECRET` is optional for local polling but required by the production webhook transport.

Generate a suitable webhook secret locally:

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
```

Keep real tokens and secrets out of Git, logs, screenshots, support messages, and shell command history.

## GitHub credential

Create a fine-grained personal access token for only the target repository.

Required repository permission:

```text
Issues: Read and write
```

Contents and Administration permissions are not required.

At runtime the bot validates repository access and Issues support, creates missing required state labels, and verifies Issues write capability.

## Production deployment on Vercel

The repository exposes a Starlette ASGI app from the root `main.py`. Vercel detects the Python app and installs dependencies from `pyproject.toml`.

1. Import this repository into Vercel.
2. Use the repository's default branch for Production (currently `master`).
3. Configure these Production environment variables:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_ALLOWED_USER_ID`
   - `TELEGRAM_WEBHOOK_SECRET`
   - `GITHUB_TOKEN`
   - `GITHUB_REPOSITORY`
4. Deploy.
5. Copy the stable production URL, for example `https://life-ops-bot.vercel.app`.
6. Register the webhook with the setup helper described below.
7. Verify webhook status and send a Telegram message.

The production Telegram endpoint is:

```text
https://<production-host>/api/telegram/webhook
```

Do not register a temporary Vercel preview URL as the normal production webhook.

## Webhook setup

Install the project locally first:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
```

Put the same Telegram configuration in the local untracked `.env`. The setup helper reads the bot token and webhook secret from configuration, so they do not need to appear in the command itself.

Register the production webhook using only the HTTPS origin (scheme + host, with no path):

```bash
life-ops-webhook set https://<production-host>
```

The helper registers:

- `/api/telegram/webhook`
- Telegram `secret_token`
- `max_connections=1`
- only `message` and `callback_query` updates

Check status:

```bash
life-ops-webhook info
```

Remove the webhook before returning to local polling:

```bash
life-ops-webhook delete
```

Only use `--drop-pending-updates` when you intentionally want to discard undelivered Telegram updates:

```bash
life-ops-webhook delete --drop-pending-updates
```

Telegram does not allow `getUpdates`/long polling while an outgoing webhook is configured.

## Webhook security and retry behavior

Incoming requests must carry the configured Telegram header:

```text
X-Telegram-Bot-Api-Secret-Token
```

A missing or incorrect secret is rejected before the HTTP body is read. After authenticated transport parsing, the exact numeric Telegram sender is checked before aiogram/domain processing or GitHub access.

Telegram retries webhook delivery when the endpoint returns a non-2xx status. Processing failures therefore return a non-2xx response, while unauthorized Telegram senders are safely ignored with success so Telegram does not retry them indefinitely.

No secret is written to GitHub Issues.

## Local development with long polling

Long polling remains useful as a local development fallback.

First make sure the webhook is removed:

```bash
life-ops-webhook delete
```

Then run:

```bash
life-ops-bot
```

The same core, Telegram router, authorization rules, GitHub adapter, and repository contract are reused by both transports.

## Reminders

Reminder scheduling is intentionally outside the webhook request lifecycle.

When reminders are implemented:

- reminder state must remain durable;
- an external durable scheduler/trigger should wake delivery;
- missed scheduler runs must be recoverable from persisted due state;
- no reminder may depend on an in-memory timer surviving a Vercel cold start.

This repository does not currently implement the final reminder scheduler.

## Validation

```bash
pytest
ruff check .
git diff --check
```

Tests use fakes and mock transports. They do not require production Telegram, GitHub, or Vercel credentials.

## Architecture boundaries

Core behavior is independent of Vercel. Vercel is the reference production host; the transport boundary is explicit so another ASGI/serverless host can reuse the same application logic.

Unauthorized Telegram users are rejected before application-level private message processing and GitHub side effects. GitHub errors surfaced to users are sanitized and never include private response bodies or credentials.

## License

MIT.
