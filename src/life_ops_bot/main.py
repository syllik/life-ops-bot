from __future__ import annotations

import asyncio
import os

from aiogram import Bot, Dispatcher

from .config import Settings
from .core import LifeOps
from .github import GitHubIssues
from .telegram import build_router


async def run() -> None:
    settings = Settings.from_env(os.environ)
    bot = Bot(token=settings.telegram_bot_token)
    dispatcher = Dispatcher()

    async with GitHubIssues(
        token=settings.github_token,
        repository=settings.life_ops_repository,
    ) as github:
        dispatcher.include_router(build_router(LifeOps(github), settings.telegram_allowed_user_id))
        try:
            await dispatcher.start_polling(bot)
        finally:
            await bot.session.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
