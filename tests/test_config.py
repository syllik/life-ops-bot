from pathlib import Path

import pytest

from life_ops_bot.config import ConfigError, Settings, load_runtime_env


def base_env() -> dict[str, str]:
    return {
        "TELEGRAM_BOT_TOKEN": " tg-token ",
        "TELEGRAM_ALLOWED_USER_ID": "123",
        "GITHUB_TOKEN": " gh-token ",
        "GITHUB_REPOSITORY": " owner/tasks ",
    }


def test_settings_from_env_requires_and_normalizes_github_repository() -> None:
    settings = Settings.from_env(base_env())

    assert settings.telegram_bot_token == "tg-token"
    assert settings.telegram_allowed_user_id == 123
    assert settings.github_token == "gh-token"
    assert settings.github_repository == "owner/tasks"


def test_load_runtime_env_reads_optional_dotenv_and_process_env_wins(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "TELEGRAM_BOT_TOKEN=file-token\n"
        "TELEGRAM_ALLOWED_USER_ID=123\n"
        "GITHUB_TOKEN=file-github-token\n"
        "GITHUB_REPOSITORY=owner/tasks\n",
        encoding="utf-8",
    )

    loaded = load_runtime_env(
        {"GITHUB_TOKEN": "runtime-github-token"},
        env_file=env_file,
    )

    assert loaded == {
        "TELEGRAM_BOT_TOKEN": "file-token",
        "TELEGRAM_ALLOWED_USER_ID": "123",
        "GITHUB_TOKEN": "runtime-github-token",
        "GITHUB_REPOSITORY": "owner/tasks",
    }


def test_load_runtime_env_without_dotenv_uses_only_process_env(tmp_path: Path) -> None:
    env = {"GITHUB_REPOSITORY": "owner/tasks"}

    assert load_runtime_env(env, env_file=tmp_path / "missing.env") == env


def test_load_runtime_env_does_not_interpolate_secret_values(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "TOKEN_PREFIX=secret\n"
        "TELEGRAM_BOT_TOKEN=${TOKEN_PREFIX}-literal\n",
        encoding="utf-8",
    )

    loaded = load_runtime_env({}, env_file=env_file)

    assert loaded["TELEGRAM_BOT_TOKEN"] == "${TOKEN_PREFIX}-literal"


def test_legacy_repository_setting_does_not_replace_required_github_repository() -> None:
    env = base_env()
    del env["GITHUB_REPOSITORY"]
    env["LIFE_OPS_" + "REPOSITORY"] = "someone/tasks"

    with pytest.raises(ConfigError, match="GITHUB_REPOSITORY is required"):
        Settings.from_env(env)


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("TELEGRAM_BOT_TOKEN", "", "TELEGRAM_BOT_TOKEN is required"),
        ("GITHUB_TOKEN", "", "GITHUB_TOKEN is required"),
        ("TELEGRAM_ALLOWED_USER_ID", "", "TELEGRAM_ALLOWED_USER_ID is required"),
        ("TELEGRAM_ALLOWED_USER_ID", "abc", "TELEGRAM_ALLOWED_USER_ID must be an integer"),
        ("TELEGRAM_ALLOWED_USER_ID", "0", "TELEGRAM_ALLOWED_USER_ID must be positive"),
        ("GITHUB_REPOSITORY", "owner", "GITHUB_REPOSITORY must be in owner/repository form"),
        ("GITHUB_REPOSITORY", "owner/", "GITHUB_REPOSITORY must be in owner/repository form"),
        ("GITHUB_REPOSITORY", "/repo", "GITHUB_REPOSITORY must be in owner/repository form"),
        (
            "GITHUB_REPOSITORY",
            "owner/repo/extra",
            "GITHUB_REPOSITORY must be in owner/repository form",
        ),
        ("GITHUB_REPOSITORY", "owner /repo", "GITHUB_REPOSITORY must be in owner/repository form"),
    ],
)
def test_settings_reject_invalid_values(key: str, value: str, message: str) -> None:
    env = base_env()
    env[key] = value

    with pytest.raises(ConfigError, match=message):
        Settings.from_env(env)
