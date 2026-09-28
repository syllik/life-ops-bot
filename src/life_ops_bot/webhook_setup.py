from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections.abc import Mapping
from urllib.parse import urlparse

import httpx

from .config import WEBHOOK_PATH, ConfigError, Settings, load_runtime_env

TELEGRAM_API = "https://api.telegram.org"
ALLOWED_UPDATES = ("message", "callback_query")


class WebhookSetupError(RuntimeError):
    """A sanitized setup error that never includes bot credentials."""


def webhook_url(base_url: str) -> str:
    parsed = urlparse(base_url.strip())
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise WebhookSetupError("production base URL must be an HTTPS origin")
    return f"https://{parsed.netloc}{WEBHOOK_PATH}"


async def configure_webhook(
    *,
    settings: Settings,
    base_url: str,
    client: httpx.AsyncClient | None = None,
) -> Mapping[str, object]:
    secret = settings.require_webhook_secret()
    return await _telegram_call(
        settings.telegram_bot_token,
        "setWebhook",
        {
            "url": webhook_url(base_url),
            "secret_token": secret,
            "max_connections": 1,
            "allowed_updates": list(ALLOWED_UPDATES),
        },
        client=client,
    )


async def get_webhook_info(
    *,
    settings: Settings,
    client: httpx.AsyncClient | None = None,
) -> Mapping[str, object]:
    return await _telegram_call(
        settings.telegram_bot_token,
        "getWebhookInfo",
        {},
        client=client,
    )


async def delete_webhook(
    *,
    settings: Settings,
    drop_pending_updates: bool = False,
    client: httpx.AsyncClient | None = None,
) -> Mapping[str, object]:
    return await _telegram_call(
        settings.telegram_bot_token,
        "deleteWebhook",
        {"drop_pending_updates": drop_pending_updates},
        client=client,
    )


async def _telegram_call(
    token: str,
    method: str,
    payload: Mapping[str, object],
    *,
    client: httpx.AsyncClient | None = None,
) -> Mapping[str, object]:
    owns_client = client is None
    api = client or httpx.AsyncClient(base_url=TELEGRAM_API, timeout=15.0)
    try:
        try:
            response = await api.post(f"/bot{token}/{method}", json=payload)
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise WebhookSetupError(f"Telegram {method} request failed") from exc
    finally:
        if owns_client:
            await api.aclose()

    if not isinstance(data, dict) or data.get("ok") is not True:
        raise WebhookSetupError(f"Telegram {method} request failed")
    result = data.get("result")
    if isinstance(result, dict):
        return result
    return {"result": result}


def _safe_info(info: Mapping[str, object]) -> dict[str, object]:
    keys = (
        "url",
        "pending_update_count",
        "max_connections",
        "allowed_updates",
        "last_error_date",
        "last_error_message",
    )
    return {key: info[key] for key in keys if key in info}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Configure the Telegram webhook without placing the bot token in shell history."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    set_parser = subparsers.add_parser("set", help="register the production webhook")
    set_parser.add_argument("base_url", help="stable production URL, for example https://app.vercel.app")

    subparsers.add_parser("info", help="show current webhook status")

    delete_parser = subparsers.add_parser(
        "delete",
        help="remove the webhook and allow polling again",
    )
    delete_parser.add_argument(
        "--drop-pending-updates",
        action="store_true",
        help="discard updates Telegram has not delivered yet",
    )
    return parser


async def _run(args: argparse.Namespace) -> int:
    settings = Settings.from_env(load_runtime_env(os.environ))
    if args.command == "set":
        result = await configure_webhook(settings=settings, base_url=args.base_url)
        print(json.dumps({"ok": True, "webhook": result}, ensure_ascii=False))
        return 0
    if args.command == "info":
        info = await get_webhook_info(settings=settings)
        print(json.dumps(_safe_info(info), ensure_ascii=False, indent=2))
        return 0
    if args.command == "delete":
        result = await delete_webhook(
            settings=settings,
            drop_pending_updates=args.drop_pending_updates,
        )
        print(json.dumps({"ok": True, "webhook": result}, ensure_ascii=False))
        return 0
    raise AssertionError("unreachable")


def main() -> None:
    args = _parser().parse_args()
    try:
        raise SystemExit(asyncio.run(_run(args)))
    except (ConfigError, WebhookSetupError) as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
