from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


class ConfigError(ValueError):
    """Raised when required runtime configuration is invalid."""


@dataclass(frozen=True, slots=True)
class Settings:
    telegram_bot_token: str
    telegram_allowed_user_id: int
    github_token: str
    life_ops_repository: str

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Settings:
        telegram_token = _required(env, "TELEGRAM_BOT_TOKEN")
        github_token = _required(env, "GITHUB_TOKEN")
        repository = env.get("LIFE_OPS_REPOSITORY", "syllik/life-ops").strip()
        if repository.count("/") != 1 or any(not part for part in repository.split("/")):
            raise ConfigError("LIFE_OPS_REPOSITORY must be in owner/repository form")

        raw_user_id = _required(env, "TELEGRAM_ALLOWED_USER_ID")
        try:
            allowed_user_id = int(raw_user_id)
        except ValueError as exc:
            raise ConfigError("TELEGRAM_ALLOWED_USER_ID must be an integer") from exc
        if allowed_user_id <= 0:
            raise ConfigError("TELEGRAM_ALLOWED_USER_ID must be positive")

        return cls(
            telegram_bot_token=telegram_token,
            telegram_allowed_user_id=allowed_user_id,
            github_token=github_token,
            life_ops_repository=repository,
        )


def _required(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    if not value:
        raise ConfigError(f"{name} is required")
    return value
