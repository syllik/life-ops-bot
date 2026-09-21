from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import life_ops_bot.main as main_module
from life_ops_bot.config import Settings


def configured_settings() -> Settings:
    return Settings(
        telegram_bot_token="tg",
        telegram_allowed_user_id=123,
        github_token="gh",
        github_repository="owner/tasks",
    )


@pytest.mark.asyncio
async def test_run_validates_repository_before_polling_and_closes_resources(monkeypatch) -> None:
    events: list[str] = []
    monkeypatch.setattr(main_module.Settings, "from_env", lambda _: configured_settings())

    bot = SimpleNamespace(session=SimpleNamespace(close=AsyncMock()))
    monkeypatch.setattr(main_module, "Bot", lambda token: bot)

    async def start_polling(_bot) -> None:
        events.append("poll")

    dispatcher = SimpleNamespace(
        include_router=lambda _: events.append("router"),
        start_polling=AsyncMock(side_effect=start_polling),
    )
    monkeypatch.setattr(main_module, "Dispatcher", lambda: dispatcher)

    class FakeGitHub:
        def __init__(self, **kwargs):
            assert kwargs == {"token": "gh", "repository": "owner/tasks"}

        async def __aenter__(self):
            events.append("github-enter")
            return self

        async def __aexit__(self, *_):
            events.append("github-exit")

        async def ensure_repository_contract(self) -> None:
            events.append("contract")

    monkeypatch.setattr(main_module, "GitHubIssues", FakeGitHub)
    monkeypatch.setattr(main_module, "LifeOps", lambda github: ("core", github))
    monkeypatch.setattr(
        main_module,
        "build_router",
        lambda core, user_id: (core, user_id),
    )

    await main_module.run()

    assert events.index("contract") < events.index("poll")
    assert events == ["github-enter", "contract", "router", "poll", "github-exit"]
    dispatcher.start_polling.assert_awaited_once_with(bot)
    bot.session.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_does_not_poll_when_repository_contract_fails_and_closes_resources(
    monkeypatch,
) -> None:
    events: list[str] = []
    monkeypatch.setattr(main_module.Settings, "from_env", lambda _: configured_settings())

    bot = SimpleNamespace(session=SimpleNamespace(close=AsyncMock()))
    monkeypatch.setattr(main_module, "Bot", lambda token: bot)
    dispatcher = SimpleNamespace(
        include_router=lambda _: events.append("router"),
        start_polling=AsyncMock(),
    )
    monkeypatch.setattr(main_module, "Dispatcher", lambda: dispatcher)

    class FakeGitHub:
        def __init__(self, **kwargs):
            assert kwargs == {"token": "gh", "repository": "owner/tasks"}

        async def __aenter__(self):
            events.append("github-enter")
            return self

        async def __aexit__(self, *_):
            events.append("github-exit")

        async def ensure_repository_contract(self) -> None:
            events.append("contract")
            raise RuntimeError("repository contract failed")

    monkeypatch.setattr(main_module, "GitHubIssues", FakeGitHub)

    with pytest.raises(RuntimeError, match="repository contract failed"):
        await main_module.run()

    assert events == ["github-enter", "contract", "github-exit"]
    dispatcher.start_polling.assert_not_awaited()
    bot.session.close.assert_awaited_once()


def test_main_calls_asyncio_run(monkeypatch) -> None:
    marker = object()
    monkeypatch.setattr(main_module, "run", lambda: marker)
    called = []
    monkeypatch.setattr(main_module.asyncio, "run", called.append)
    main_module.main()
    assert called == [marker]
