import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import life_ops_bot.webhook as webhook
from life_ops_bot.config import Settings
from life_ops_bot.github import GitHubError


def configured_settings() -> Settings:
    return Settings(
        telegram_bot_token="tg",
        telegram_allowed_user_id=123,
        github_token="gh",
        github_repository="owner/tasks",
        telegram_webhook_secret="secret_123",
    )


def scope(
    *,
    path: str = "/api/telegram/webhook",
    method: str = "POST",
    secret: bytes | None = b"secret_123",
):
    headers = [] if secret is None else [(b"x-telegram-bot-api-secret-token", secret)]
    return {"type": "http", "path": path, "method": method, "headers": headers}


def message_payload(*, user_id: int = 123) -> dict[str, object]:
    return {
        "update_id": 1,
        "message": {
            "message_id": 2,
            "from": {"id": user_id, "is_bot": False, "first_name": "User"},
            "chat": {"id": user_id, "type": "private"},
            "date": 1,
            "text": "private text",
        },
    }


def callback_payload(*, user_id: int = 123) -> dict[str, object]:
    return {
        "update_id": 2,
        "callback_query": {
            "id": "callback",
            "from": {"id": user_id, "is_bot": False, "first_name": "User"},
            "chat_instance": "x",
            "data": "done:1",
        },
    }


async def call_app(
    monkeypatch,
    payload: object = None,
    *,
    request_scope=None,
    body: bytes | None = None,
):
    monkeypatch.setattr(webhook.Settings, "from_env", lambda _: configured_settings())
    raw = body if body is not None else json.dumps(payload).encode()
    messages = [{"type": "http.request", "body": raw, "more_body": False}]
    sent = []

    async def receive():
        return messages.pop(0)

    async def send(message):
        sent.append(message)

    await webhook.app(request_scope or scope(), receive, send)
    return sent


def status(sent) -> int:
    return sent[0]["status"]


@pytest.mark.asyncio
async def test_valid_authorized_message_is_processed(monkeypatch) -> None:
    bot = SimpleNamespace(session=SimpleNamespace(close=AsyncMock()))
    process = AsyncMock()
    marker = object()
    monkeypatch.setattr(webhook, "_make_bot", lambda _: bot)
    monkeypatch.setattr(webhook, "_parse_update", lambda payload, _: marker)
    monkeypatch.setattr(webhook, "process_update", process)

    sent = await call_app(monkeypatch, message_payload())

    assert status(sent) == 200
    process.assert_awaited_once_with(configured_settings(), bot, marker)
    bot.session.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_valid_authorized_callback_is_processed(monkeypatch) -> None:
    bot = SimpleNamespace(session=SimpleNamespace(close=AsyncMock()))
    process = AsyncMock()
    monkeypatch.setattr(webhook, "_make_bot", lambda _: bot)
    monkeypatch.setattr(webhook, "_parse_update", lambda payload, _: payload)
    monkeypatch.setattr(webhook, "process_update", process)

    sent = await call_app(monkeypatch, callback_payload())

    assert status(sent) == 200
    process.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("secret", [None, b"wrong"])
async def test_bad_webhook_secret_is_rejected_before_body_read(monkeypatch, secret) -> None:
    monkeypatch.setattr(webhook.Settings, "from_env", lambda _: configured_settings())
    sent = []

    async def receive():
        raise AssertionError("body must not be read before webhook authentication")

    async def send(message):
        sent.append(message)

    await webhook.app(scope(secret=secret), receive, send)

    assert status(sent) == 401


@pytest.mark.asyncio
async def test_missing_webhook_configuration_fails_closed_before_body(monkeypatch) -> None:
    settings = configured_settings()
    settings = Settings(
        telegram_bot_token=settings.telegram_bot_token,
        telegram_allowed_user_id=settings.telegram_allowed_user_id,
        github_token=settings.github_token,
        github_repository=settings.github_repository,
    )
    monkeypatch.setattr(webhook.Settings, "from_env", lambda _: settings)
    sent = []

    async def receive():
        raise AssertionError("body must not be read with invalid configuration")

    async def send(message):
        sent.append(message)

    await webhook.app(scope(), receive, send)

    assert status(sent) == 500


@pytest.mark.asyncio
async def test_unauthorized_sender_never_builds_bot_or_calls_github(monkeypatch) -> None:
    monkeypatch.setattr(
        webhook,
        "_make_bot",
        lambda _: (_ for _ in ()).throw(AssertionError("must not build Telegram bot")),
    )

    sent = await call_app(monkeypatch, message_payload(user_id=999))

    assert status(sent) == 200


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("request_scope", "expected"),
    [
        (scope(path="/other"), 404),
        (scope(method="GET"), 405),
    ],
)
async def test_route_and_method_are_restricted(monkeypatch, request_scope, expected) -> None:
    sent = await call_app(monkeypatch, message_payload(), request_scope=request_scope)
    assert status(sent) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [b"{", b"[]"])
async def test_malformed_or_non_object_json_is_rejected(monkeypatch, body) -> None:
    sent = await call_app(monkeypatch, body=body)
    assert status(sent) == 400


@pytest.mark.asyncio
async def test_oversized_body_is_rejected(monkeypatch) -> None:
    monkeypatch.setattr(webhook, "MAX_BODY_BYTES", 2)
    sent = await call_app(monkeypatch, body=b"123")
    assert status(sent) == 413


@pytest.mark.asyncio
async def test_invalid_update_is_rejected_and_bot_is_closed(monkeypatch) -> None:
    bot = SimpleNamespace(session=SimpleNamespace(close=AsyncMock()))
    monkeypatch.setattr(webhook, "_make_bot", lambda _: bot)
    monkeypatch.setattr(
        webhook,
        "_parse_update",
        lambda *_: (_ for _ in ()).throw(ValueError("bad update")),
    )

    sent = await call_app(monkeypatch, message_payload())

    assert status(sent) == 400
    bot.session.close.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected"),
    [(GitHubError("safe"), 503), (RuntimeError("unexpected"), 500)],
)
async def test_processing_failures_return_retryable_status(monkeypatch, error, expected) -> None:
    bot = SimpleNamespace(session=SimpleNamespace(close=AsyncMock()))
    monkeypatch.setattr(webhook, "_make_bot", lambda _: bot)
    monkeypatch.setattr(webhook, "_parse_update", lambda payload, _: payload)
    monkeypatch.setattr(webhook, "process_update", AsyncMock(side_effect=error))

    sent = await call_app(monkeypatch, message_payload())

    assert status(sent) == expected
    bot.session.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_bot_construction_failure_returns_server_error(monkeypatch) -> None:
    monkeypatch.setattr(
        webhook,
        "_make_bot",
        lambda _: (_ for _ in ()).throw(RuntimeError("invalid token")),
    )

    sent = await call_app(monkeypatch, message_payload())

    assert status(sent) == 500


@pytest.mark.asyncio
async def test_process_update_validates_contract_once_per_warm_instance(monkeypatch) -> None:
    webhook._repository_contract_ready = False
    events = []
    dispatcher = SimpleNamespace(
        include_router=lambda router: events.append(("router", router)),
        feed_update=AsyncMock(),
    )
    monkeypatch.setattr(webhook, "_make_dispatcher", lambda: dispatcher)
    monkeypatch.setattr(webhook, "_build_router", lambda core, user_id: ("built", core, user_id))
    monkeypatch.setattr(webhook, "LifeOps", lambda github: ("core", github))

    class FakeGitHub:
        def __init__(self, **kwargs):
            assert kwargs == {"token": "gh", "repository": "owner/tasks"}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def ensure_repository_contract(self):
            events.append(("contract",))

    monkeypatch.setattr(webhook, "GitHubIssues", FakeGitHub)
    settings = configured_settings()
    bot = object()

    await webhook.process_update(settings, bot, "one")
    await webhook.process_update(settings, bot, "two")

    assert events.count(("contract",)) == 1
    assert dispatcher.feed_update.await_count == 2


@pytest.mark.asyncio
async def test_lifespan_and_non_http_scopes_are_safe() -> None:
    messages = [
        {"type": "lifespan.startup"},
        {"type": "lifespan.shutdown"},
    ]
    sent = []

    async def receive():
        return messages.pop(0)

    async def send(message):
        sent.append(message)

    await webhook.app({"type": "lifespan"}, receive, send)
    assert sent == [
        {"type": "lifespan.startup.complete"},
        {"type": "lifespan.shutdown.complete"},
    ]

    sent.clear()
    await webhook.app({"type": "websocket"}, receive, send)
    assert sent == []


def test_webhook_router_enables_github_error_propagation(monkeypatch) -> None:
    import life_ops_bot.telegram as telegram_module

    calls = []

    def fake_build_router(life_ops, allowed_user_id, *, propagate_github_errors):
        calls.append((life_ops, allowed_user_id, propagate_github_errors))
        return "router"

    monkeypatch.setattr(telegram_module, "build_router", fake_build_router)

    assert webhook._build_router("core", 123) == "router"
    assert calls == [("core", 123, True)]
