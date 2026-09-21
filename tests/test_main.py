from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import life_ops_bot.main as main_module
from life_ops_bot.config import Settings


@pytest.mark.asyncio
async def test_run_wires_polling_and_closes_bot(monkeypatch) -> None:
    settings = Settings("tg", 123, "gh", "syllik/life-ops")
    monkeypatch.setattr(main_module.Settings, "from_env", lambda _: settings)

    bot = SimpleNamespace(session=SimpleNamespace(close=AsyncMock()))
    monkeypatch.setattr(main_module, "Bot", lambda token: bot)

    dispatcher = SimpleNamespace(include_router=lambda _: None, start_polling=AsyncMock())
    monkeypatch.setattr(main_module, "Dispatcher", lambda: dispatcher)

    class FakeGitHub:
        def __init__(self, **kwargs):
            assert kwargs == {"token": "gh", "repository": "syllik/life-ops"}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

    monkeypatch.setattr(main_module, "GitHubIssues", FakeGitHub)
    monkeypatch.setattr(main_module, "LifeOps", lambda github: ("core", github))
    monkeypatch.setattr(main_module, "build_router", lambda core, user_id: (core, user_id))

    await main_module.run()

    dispatcher.start_polling.assert_awaited_once_with(bot)
    bot.session.close.assert_awaited_once()


def test_main_calls_asyncio_run(monkeypatch) -> None:
    marker = object()
    monkeypatch.setattr(main_module, "run", lambda: marker)
    called = []
    monkeypatch.setattr(main_module.asyncio, "run", called.append)
    main_module.main()
    assert called == [marker]
