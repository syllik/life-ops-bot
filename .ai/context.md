# Life Ops Bot context

## Product

`life-ops-bot` is a small public Telegram bot that operates the user's private Life Ops stored as GitHub Issues.

Related repository:

- `syllik/life-ops` — private durable data store and task model
- `syllik/life-ops-bot` — public MIT runtime/client

The private repository contract is authoritative for issue semantics and taxonomy.

## Goal

Make capturing and operating personal tasks from Telegram faster than opening GitHub, while keeping GitHub as the only durable task authority.

## MVP architecture

```text
Telegram Bot API (long polling)
          |
          v
authorization by exact numeric user ID
          |
          v
capture/parser
          |
          +--> LLM classifier (replaceable)
          |      |
          |      +--> title
          |      +--> type
          |      +--> area
          |      +--> state
          |
          v
GitHub adapter
          |
          v
private syllik/life-ops Issues
```

No GitHub Project and no separate application database in the MVP.

## Life Ops mapping

Issue:
- title = normalized concise title
- body = original note + useful context + optional machine metadata
- labels = semantic area/type/state
- open = active
- closed = done

Types:
- task
- research
- idea
- decision
- reference

Sparse states:
- no state label = normal actionable item
- inbox = needs classification/clarification
- now = current focus
- waiting = blocked / waiting for an event
- later = deliberately deferred

## Capture

MVP accepts:
- text
- links
- forwarded Telegram messages

Default:
1. exact-user authorization
2. preserve original content
3. classify
4. create Issue
5. confirm Saved

If the LLM is unavailable or classification is uncertain, create a safe Inbox issue containing the original input instead of dropping it.

## Telegram UX

Initial saved-item actions:
- Done
- Later
- GitHub

Next navigation:
- Now
- Inbox
- Areas
- Reminders
- Later
- Search

Do not build a Mini App for MVP.

## Reminders

Reminder support is a later phase after capture/navigation.

Durable reminder metadata must live in GitHub and remain reconstructable after restart.

Planned capabilities:
- exact datetime
- relative datetime
- recurrence
- snooze
- dependency/manual waiting

Location triggers are explicitly out of scope.

## Runtime

Target production host:
- dedicated local OS user on a friend's machine in Georgia
- long-running daemon/container
- Telegram long polling
- no inbound public port
- auto restart

The host may cache ephemeral data in memory, but GitHub remains the durable source of truth.

## Secrets / configuration

Expected configuration:
- TELEGRAM_BOT_TOKEN
- TELEGRAM_ALLOWED_USER_ID
- GITHUB_TOKEN
- LIFE_OPS_REPOSITORY=syllik/life-ops
- TIMEZONE
- optional LLM_API_KEY
- optional LLM_MODEL
- optional LLM_BASE_URL

Do not commit any real values.

## Security

Single-user authorization is a hard boundary. Unauthorized senders must be rejected before:
- LLM calls
- GitHub reads/writes involving private data
- message-body logging
- any persistent or external side effect

The public bot repository must never contain private Life Ops Issue content or exported personal backlog.

## LLM

Use an adapter so the provider can be changed later.

The classifier should receive only the current capture plus the minimum taxonomy/context necessary. Do not send the full private backlog to a cloud model by default.

## Analogue research decision

Already reviewed:
- `nxt-am/tg-bot-reminders`: useful aiogram/timezone/keyboard reference but DB + APScheduler architecture conflicts with GitHub-as-state and its default user handling is unsuitable for this single-user privacy boundary.
- `mtzanidakis/dodo`: stronger reference for allowlisting, polling/backoff, operational hygiene, backups/migrations, but much larger and DB-centric.

Decision: small greenfield bot, reusing standard libraries and reference patterns rather than forking either project.

## Delivery phases

1. bootstrap + tests
2. Telegram authorization + capture
3. GitHub Issues adapter
4. classifier + Inbox fallback
5. Done / Later actions
6. navigation/search
7. reminders
8. deployment hardening
