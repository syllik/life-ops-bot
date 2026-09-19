from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from life_ops_bot.core import Capture, Issue
from life_ops_bot.github import GitHubError
from life_ops_bot.telegram import SAVE_ERROR, handle_message


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


@pytest.mark.asyncio
async def test_authorized_text_link_is_saved_and_replied_with_actions() -> None:
    life_ops = FakeLifeOps()
    message = fake_message(text="https://example.com/a?x=1&y=2")

    await handle_message(message, life_ops, 123)

    assert life_ops.captures == [Capture("https://example.com/a?x=1&y=2", -99, 7, None)]
    message.answer.assert_awaited_once()
    args, kwargs = message.answer.await_args
    assert args[0] == "✅ Saved #42\nhttps://github.com/syllik/life-ops/issues/42"
    assert kwargs["disable_web_page_preview"] is True
    buttons = kwargs["reply_markup"].inline_keyboard[0]
    assert [(b.text, b.callback_data, b.url) for b in buttons] == [
        ("Done", "done:42", None),
        ("Later", "later:42", None),
        ("GitHub", None, "https://github.com/syllik/life-ops/issues/42"),
    ]


@pytest.mark.asyncio
async def test_unauthorized_message_has_no_processing_or_side_effects() -> None:
    life_ops = FakeLifeOps()

    class PrivateMessage:
        from_user = SimpleNamespace(id=999)

        @property
        def text(self):
            raise AssertionError("unauthorized body must not be accessed")

        answer = AsyncMock()

    message = PrivateMessage()
    await handle_message(message, life_ops, 123)
    assert life_ops.captures == []
    message.answer.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_sender_or_non_text_is_ignored() -> None:
    life_ops = FakeLifeOps()
    missing_sender = fake_message()
    missing_sender.from_user = None
    await handle_message(missing_sender, life_ops, 123)

    no_text = fake_message(text=None)
    await handle_message(no_text, life_ops, 123)

    assert life_ops.captures == []
    missing_sender.answer.assert_not_awaited()
    no_text.answer.assert_not_awaited()


@pytest.mark.asyncio
async def test_github_failure_reports_error_without_false_success() -> None:
    life_ops = FakeLifeOps()
    life_ops.capture_error = True
    message = fake_message(text="private input")

    await handle_message(message, life_ops, 123)

    message.answer.assert_awaited_once_with(SAVE_ERROR)
    assert "private input" not in message.answer.await_args.args[0]
    assert "Saved" not in message.answer.await_args.args[0]

