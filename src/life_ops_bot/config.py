from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values


class ConfigError(ValueError):
    """Raised when required runtime configuration is invalid."""


@dataclass(frozen=True, slots=True)
class Settings:
    telegram_bot_token: str
    telegram_allowed_user_id: int
    github_token: str
    github_repository: str

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Settings:
        telegram_token = _required(env, "TELEGRAM_BOT_TOKEN")
        github_token = _required(env, "GITHUB_TOKEN")
        repository = _required(env, "GITHUB_REPOSITORY")
        if (
            repository.count("/") != 1
            or any(not part for part in repository.split("/"))
            or any(character.isspace() for character in repository)
        ):
            raise ConfigError("GITHUB_REPOSITORY must be in owner/repository form")

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
            github_repository=repository,
        )


def load_runtime_env(
    env: Mapping[str, str],
    env_file: str | Path = ".env",
) -> dict[str, str]:
    """Merge an optional local env file with the process environment.

    Process environment variables take precedence so deployment platforms can
    inject runtime configuration without depending on a local file.
    """

    path = Path(env_file)
    file_values: dict[str, str] = {}
    if path.is_file():
        file_values = {
            key: value
            for key, value in dotenv_values(path, interpolate=False).items()
            if value is not None
        }

    merged = file_values
    merged.update(env)
    return merged


def _required(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    if not value:
        raise ConfigError(f"{name} is required")
    return value
