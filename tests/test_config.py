import pytest

from life_ops_bot.config import ConfigError, Settings


def test_settings_from_env() -> None:
    settings = Settings.from_env(
        {
            "TELEGRAM_BOT_TOKEN": " tg-token ",
            "TELEGRAM_ALLOWED_USER_ID": "123",
            "GITHUB_TOKEN": " gh-token ",
        }
    )
    assert settings.telegram_bot_token == "tg-token"
    assert settings.telegram_allowed_user_id == 123
    assert settings.github_token == "gh-token"
    assert settings.life_ops_repository == "syllik/life-ops"


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({}, "TELEGRAM_BOT_TOKEN is required"),
        ({"TELEGRAM_BOT_TOKEN": "x"}, "GITHUB_TOKEN is required"),
        (
            {"TELEGRAM_BOT_TOKEN": "x", "GITHUB_TOKEN": "y"},
            "TELEGRAM_ALLOWED_USER_ID is required",
        ),
        (
            {
                "TELEGRAM_BOT_TOKEN": "x",
                "GITHUB_TOKEN": "y",
                "TELEGRAM_ALLOWED_USER_ID": "abc",
            },
            "TELEGRAM_ALLOWED_USER_ID must be an integer",
        ),
        (
            {
                "TELEGRAM_BOT_TOKEN": "x",
                "GITHUB_TOKEN": "y",
                "TELEGRAM_ALLOWED_USER_ID": "0",
            },
            "TELEGRAM_ALLOWED_USER_ID must be positive",
        ),
        (
            {
                "TELEGRAM_BOT_TOKEN": "x",
                "GITHUB_TOKEN": "y",
                "TELEGRAM_ALLOWED_USER_ID": "1",
                "LIFE_OPS_REPOSITORY": "invalid",
            },
            "LIFE_OPS_REPOSITORY must be in owner/repository form",
        ),
    ],
)
def test_settings_reject_invalid_env(env: dict[str, str], message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        Settings.from_env(env)
