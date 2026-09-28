from argparse import Namespace
from unittest.mock import AsyncMock

import httpx
import pytest

import life_ops_bot.webhook_setup as setup
from life_ops_bot.config import Settings


def settings() -> Settings:
    return Settings(
        telegram_bot_token="tg-secret-token",
        telegram_allowed_user_id=123,
        github_token="gh",
        github_repository="owner/tasks",
        telegram_webhook_secret="hook_secret",
    )


def client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url="https://api.telegram.org",
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.parametrize(
    ("base_url", "expected"),
    [
        ("https://example.vercel.app", "https://example.vercel.app/api/telegram/webhook"),
        (" https://example.vercel.app/ ", "https://example.vercel.app/api/telegram/webhook"),
        (
            "https://example.com/base",
            "https://example.com/base/api/telegram/webhook",
        ),
    ],
)
def test_webhook_url(base_url: str, expected: str) -> None:
    assert setup.webhook_url(base_url) == expected


@pytest.mark.parametrize(
    "base_url",
    [
        "http://example.com",
        "example.com",
        "https://",
        "https://example.com?a=1",
        "https://example.com#x",
    ],
)
def test_webhook_url_requires_https_without_query_or_fragment(base_url: str) -> None:
    with pytest.raises(setup.WebhookSetupError, match="HTTPS"):
        setup.webhook_url(base_url)


@pytest.mark.asyncio
async def test_configure_webhook_uses_secret_single_connection_and_expected_updates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/bottg-secret-token/setWebhook"
        payload = request.read().decode()
        assert '"url":"https://example.vercel.app/api/telegram/webhook"' in payload
        assert '"secret_token":"hook_secret"' in payload
        assert '"max_connections":1' in payload
        assert '"allowed_updates":["message","callback_query"]' in payload
        return httpx.Response(200, json={"ok": True, "result": True})

    async with client(handler) as api:
        result = await setup.configure_webhook(
            settings=settings(),
            base_url="https://example.vercel.app",
            client=api,
        )

    assert result == {"result": True}


@pytest.mark.asyncio
async def test_info_and_delete_webhook_calls() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.url.path, request.read().decode()))
        if request.url.path.endswith("/getWebhookInfo"):
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "result": {
                        "url": "https://example.vercel.app/api/telegram/webhook",
                        "pending_update_count": 0,
                    },
                },
            )
        return httpx.Response(200, json={"ok": True, "result": True})

    async with client(handler) as api:
        info = await setup.get_webhook_info(settings=settings(), client=api)
        deleted = await setup.delete_webhook(
            settings=settings(),
            drop_pending_updates=True,
            client=api,
        )

    assert info["pending_update_count"] == 0
    assert deleted == {"result": True}
    assert calls[0][0].endswith("/getWebhookInfo")
    assert '"drop_pending_updates":true' in calls[1][1]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500, text="private upstream detail tg-secret-token"),
        httpx.Response(200, json={"ok": False, "description": "private detail"}),
        httpx.Response(200, text="not-json"),
    ],
)
async def test_setup_errors_are_sanitized(response: httpx.Response) -> None:
    async with client(lambda _: response) as api:
        with pytest.raises(setup.WebhookSetupError) as exc_info:
            await setup.get_webhook_info(settings=settings(), client=api)

    message = str(exc_info.value)
    assert "tg-secret-token" not in message
    assert "private" not in message


def test_safe_info_keeps_only_operational_fields() -> None:
    assert setup._safe_info(
        {
            "url": "https://example",
            "pending_update_count": 2,
            "max_connections": 1,
            "allowed_updates": ["message"],
            "last_error_message": "x",
            "secret": "do-not-print",
        }
    ) == {
        "url": "https://example",
        "pending_update_count": 2,
        "max_connections": 1,
        "allowed_updates": ["message"],
        "last_error_message": "x",
    }


def test_parser_supports_set_info_and_delete() -> None:
    parser = setup._parser()
    assert parser.parse_args(["set", "https://example.com"]).command == "set"
    assert parser.parse_args(["info"]).command == "info"
    deleted = parser.parse_args(["delete", "--drop-pending-updates"])
    assert deleted.command == "delete"
    assert deleted.drop_pending_updates is True


@pytest.mark.asyncio
async def test_run_set_info_and_delete_commands(monkeypatch, capsys) -> None:
    monkeypatch.setattr(setup.Settings, "from_env", lambda _: settings())

    set_call = AsyncMock(return_value={"result": True})
    monkeypatch.setattr(setup, "configure_webhook", set_call)
    assert await setup._run(Namespace(command="set", base_url="https://example.com")) == 0
    assert '"ok": true' in capsys.readouterr().out
    set_call.assert_awaited_once()

    info_call = AsyncMock(
        return_value={
            "url": "https://example.com/api/telegram/webhook",
            "pending_update_count": 0,
            "secret": "must-not-print",
        }
    )
    monkeypatch.setattr(setup, "get_webhook_info", info_call)
    assert await setup._run(Namespace(command="info")) == 0
    output = capsys.readouterr().out
    assert "pending_update_count" in output
    assert "must-not-print" not in output

    delete_call = AsyncMock(return_value={"result": True})
    monkeypatch.setattr(setup, "delete_webhook", delete_call)
    assert (
        await setup._run(
            Namespace(command="delete", drop_pending_updates=True)
        )
        == 0
    )
    assert '"ok": true' in capsys.readouterr().out
    delete_call.assert_awaited_once_with(
        settings=settings(),
        drop_pending_updates=True,
    )


@pytest.mark.asyncio
async def test_run_rejects_unknown_command(monkeypatch) -> None:
    monkeypatch.setattr(setup.Settings, "from_env", lambda _: settings())
    with pytest.raises(AssertionError, match="unreachable"):
        await setup._run(Namespace(command="unknown"))
