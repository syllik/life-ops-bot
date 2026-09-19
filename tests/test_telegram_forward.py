from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram.types import (
    Chat,
    MessageOriginChannel,
    MessageOriginChat,
    MessageOriginHiddenUser,
    MessageOriginUser,
    User,
)

from life_ops_bot.core import Capture, Issue
from life_ops_bot.github import GitHubError
from life_ops_bot.telegram import build_router, describe_forward_origin


class FakeLifeOps:
    def __init__(self) -> None:
        self.captures: list[Capture] = []
        self.done_calls: list[int] = []
        self.later_calls: list[int] = []
        self.capture_error = False
        self.action_error = False

    async def capture(self, capture: Capture) -> Issue:
        self.captures.append(capture)
        if self.capture_error:
            raise GitHubError("internal")
        return Issue(42, "https://github.com/syllik/life-ops/issues/42", "Title")

    async def done(self, issue_number: int) -> Issue:
        self.done_calls.append(issue_number)
        if self.action_error:
            raise GitHubError("internal")
        return Issue(issue_number, "https://example", "x", state="closed")

    async def later(self, issue_number: int) -> Issue:
        self.later_calls.append(issue_number)
        if self.action_error:
            raise GitHubError("internal")
        return Issue(issue_number, "https://example", "x", ("state:later",))


def fake_message(*, user_id: int = 123, text: str | None = "hello", forward_origin=None):
    return SimpleNamespace(
        from_user=SimpleNamespace(id=user_id),
        text=text,
        chat=SimpleNamespace(id=-99),
        message_id=7,
        forward_origin=forward_origin,
        answer=AsyncMock(),
    )


def fake_callback(*, user_id: int = 123, data: str | None = "done:42"):
    return SimpleNamespace(
        from_user=SimpleNamespace(id=user_id),
        data=data,
        answer=AsyncMock(),
    )

def test_describe_forward_origin_variants() -> None:
    dt = datetime.now(timezone.utc)
    user = User(id=1, is_bot=False, first_name="Alice", username="alice")
    chat = Chat(id=-10, type="group", title="Group")
    channel = Chat(id=-20, type="channel", title="Channel")

    assert describe_forward_origin(fake_message(forward_origin=None)) is None
    assert describe_forward_origin(
        fake_message(forward_origin=MessageOriginUser(type="user", date=dt, sender_user=user))
    ) == "user @alice (id=1)"
    assert describe_forward_origin(
        fake_message(
            forward_origin=MessageOriginHiddenUser(
                type="hidden_user", date=dt, sender_user_name="Hidden"
            )
        )
    ) == "hidden user Hidden"
    assert describe_forward_origin(
        fake_message(forward_origin=MessageOriginChat(type="chat", date=dt, sender_chat=chat))
    ) == "chat Group (id=-10)"
    assert describe_forward_origin(
        fake_message(
            forward_origin=MessageOriginChannel(
                type="channel", date=dt, chat=channel, message_id=55
            )
        )
    ) == "channel Channel (id=-20), message_id=55"

    no_username = User(id=2, is_bot=False, first_name="Bob")
    assert describe_forward_origin(
        fake_message(
            forward_origin=MessageOriginUser(type="user", date=dt, sender_user=no_username)
        )
    ) == "user Bob (id=2)"

    assert (
        describe_forward_origin(fake_message(forward_origin=object()))
        == "unknown forward origin"
    )


def test_build_router_registers_text_and_callback_handlers() -> None:
    router = build_router(FakeLifeOps(), 123)
    assert len(router.observers["message"].handlers) == 1
    assert len(router.observers["callback_query"].handlers) == 1
