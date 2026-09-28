from __future__ import annotations

import hmac
import json
import os
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from .config import WEBHOOK_PATH, ConfigError, Settings, load_runtime_env
from .core import LifeOps
from .github import GitHubError, GitHubIssues

WEBHOOK_SECRET_HEADER = b"x-telegram-bot-api-secret-token"
MAX_BODY_BYTES = 1024 * 1024

Scope = Mapping[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]

_repository_contract_ready = False


async def app(scope: Scope, receive: Receive, send: Send) -> None:
    if scope.get("type") == "lifespan":
        await _handle_lifespan(receive, send)
        return
    if scope.get("type") != "http":
        return
    if scope.get("path") != WEBHOOK_PATH:
        await _respond(send, 404)
        return
    if scope.get("method") != "POST":
        await _respond(send, 405, headers=((b"allow", b"POST"),))
        return

    try:
        settings = Settings.from_env(load_runtime_env(os.environ))
        expected_secret = settings.require_webhook_secret()
    except ConfigError:
        await _respond(send, 500)
        return

    provided_secret = _header(scope, WEBHOOK_SECRET_HEADER)
    if provided_secret is None or not hmac.compare_digest(
        provided_secret,
        expected_secret.encode("ascii"),
    ):
        await _respond(send, 401)
        return

    try:
        body = await _read_body(receive)
    except (ValueError, TypeError):
        await _respond(send, 413)
        return

    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        await _respond(send, 400)
        return
    if not isinstance(payload, dict):
        await _respond(send, 400)
        return

    sender_id = _telegram_sender_id(payload)
    if sender_id != settings.telegram_allowed_user_id:
        await _respond(send, 200)
        return

    try:
        bot = _make_bot(settings.telegram_bot_token)
    except Exception:
        await _respond(send, 500)
        return

    try:
        try:
            update = _parse_update(payload, bot)
        except (TypeError, ValueError):
            await _respond(send, 400)
            return

        try:
            await process_update(settings, bot, update)
        except GitHubError as exc:
            await _respond(send, 503 if exc.retryable else 200)
            return
        except Exception:
            await _respond(send, 500)
            return
    finally:
        await bot.session.close()

    await _respond(send, 200)


async def process_update(settings: Settings, bot: Any, update: Any) -> None:
    global _repository_contract_ready

    dispatcher = _make_dispatcher()
    async with GitHubIssues(
        token=settings.github_token,
        repository=settings.github_repository,
    ) as github:
        if not _repository_contract_ready:
            await github.ensure_repository_contract()
            _repository_contract_ready = True
        dispatcher.include_router(
            _build_router(LifeOps(github), settings.telegram_allowed_user_id)
        )
        await dispatcher.feed_update(bot, update)


def _make_bot(token: str) -> Any:  # pragma: no cover
    from aiogram import Bot

    return Bot(token=token)


def _parse_update(payload: Mapping[str, Any], bot: Any) -> Any:  # pragma: no cover
    from aiogram.types import Update

    return Update.model_validate(payload, context={"bot": bot})


def _make_dispatcher() -> Any:  # pragma: no cover
    from aiogram import Dispatcher

    return Dispatcher()


def _build_router(life_ops: LifeOps, allowed_user_id: int) -> Any:  # pragma: no cover
    from .telegram import build_router

    return build_router(
        life_ops,
        allowed_user_id,
        propagate_github_errors=True,
    )


async def _handle_lifespan(receive: Receive, send: Send) -> None:
    while True:
        message = await receive()
        message_type = message.get("type")
        if message_type == "lifespan.startup":
            await send({"type": "lifespan.startup.complete"})
        elif message_type == "lifespan.shutdown":
            await send({"type": "lifespan.shutdown.complete"})
            return


def _telegram_sender_id(payload: Mapping[str, Any]) -> int | None:
    for update_key in ("message", "callback_query"):
        update = payload.get(update_key)
        if not isinstance(update, Mapping):
            continue
        sender = update.get("from")
        if not isinstance(sender, Mapping):
            continue
        sender_id = sender.get("id")
        if isinstance(sender_id, int) and not isinstance(sender_id, bool):
            return sender_id
    return None


def _header(scope: Scope, name: bytes) -> bytes | None:
    headers = scope.get("headers", ())
    for raw_name, raw_value in headers:
        if raw_name.lower() == name:
            return raw_value
    return None


async def _read_body(receive: Receive) -> bytes:
    body = bytearray()
    while True:
        message = await receive()
        message_type = message.get("type")
        if message_type == "http.disconnect":
            raise ValueError("request disconnected")
        if message_type != "http.request":
            continue
        chunk = message.get("body", b"")
        if not isinstance(chunk, bytes):
            raise TypeError("request body chunk must be bytes")
        body.extend(chunk)
        if len(body) > MAX_BODY_BYTES:
            raise ValueError("request body too large")
        if not message.get("more_body", False):
            return bytes(body)


async def _respond(
    send: Send,
    status: int,
    *,
    headers: tuple[tuple[bytes, bytes], ...] = (),
) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"text/plain; charset=utf-8"), *headers],
        }
    )
    await send({"type": "http.response.body", "body": b"OK" if status == 200 else b""})
