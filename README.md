# life-ops-bot

Small Telegram interface for a GitHub-hosted personal task and reminder system.

The durable data lives in the private `syllik/life-ops` repository. This public repository contains only the bot code and documentation.

## MVP

```text
Telegram
   |
   v
life-ops-bot
   |
   +--> classify captured text
   |
   +--> GitHub Issues in syllik/life-ops
```

GitHub Issues are the source of truth. The bot does not own a separate application database.

Initial scope:

- accept text, links, and forwarded Telegram messages
- allow only one configured Telegram user ID
- create and update GitHub Issues
- preserve the original captured text
- classify into `area:*`, `type:*`, and sparse `state:*` labels
- close an Issue for Done
- support Later / Now
- expose compact navigation and search
- later add GitHub-backed reminders

Out of scope for the MVP:

- GitHub Project
- SQLite or another application database
- web UI
- webhook/public HTTP server
- location/geofencing
- multi-user support

## Security

The bot must reject unauthorized Telegram users before any processing or persistence.

Secrets stay outside Git:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_ALLOWED_USER_ID`
- `GITHUB_TOKEN`
- LLM provider credentials when used

The GitHub credential should have the minimum access required to operate on `syllik/life-ops`.

## Analogue decision

Existing projects were reviewed before starting this tool, including `nxt-am/tg-bot-reminders` and `mtzanidakis/dodo`.

They provide useful reference patterns for Telegram UX, timezone handling, allowlisting, polling/backoff, and operations. They are not used as a fork base because the current Life Ops architecture is GitHub-Issues-first and intentionally avoids their database/scheduler-centric application state. Reusing a fork would require deleting most of the upstream architecture.

## License

MIT.
