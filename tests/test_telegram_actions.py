from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from life_ops_bot.core import Capture, Issue
from life_ops_bot.github import GitHubError
from life_ops_bot.telegram import (
    ACTION_ERROR,
    handle_callback,
    parse_callback,
    saved_keyboard,
)


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
async def test_done_and_later_callbacks_and_failures() -> None:
    life_ops = FakeLifeOps()
    done = fake_callback(data="done:42")
    later = fake_callback(data="later:43")

    await handle_callback(done, life_ops, 123)
    await handle_callback(later, life_ops, 123)

    assert life_ops.done_calls == [42]
    assert life_ops.later_calls == [43]
    done.answer.assert_awaited_once_with("Done")
    later.answer.assert_awaited_once_with("Moved to Later")

    life_ops.action_error = True
    failed = fake_callback(data="done:44")
    await handle_callback(failed, life_ops, 123)
    failed.answer.assert_awaited_once_with(ACTION_ERROR, show_alert=True)


@pytest.mark.asyncio
async def test_unauthorized_callback_does_not_call_core_or_answer() -> None:
    life_ops = FakeLifeOps()
    callback = fake_callback(user_id=999, data="done:42")
    await handle_callback(callback, life_ops, 123)
    assert life_ops.done_calls == []
    callback.answer.assert_not_awaited()


@pytest.mark.asyncio
async def test_invalid_callback_is_rejected_without_github_action() -> None:
    life_ops = FakeLifeOps()
    callback = fake_callback(data="bad")
    await handle_callback(callback, life_ops, 123)
    assert life_ops.done_calls == []
    assert life_ops.later_calls == []
    callback.answer.assert_awaited_once_with(ACTION_ERROR, show_alert=True)


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ("done:1", ("done", 1)),
        ("later:9", ("later", 9)),
        (None, None),
        ("done", None),
        ("now:1", None),
        ("done:nope", None),
        ("done:0", None),
    ],
)
def test_parse_callback(data, expected) -> None:
    assert parse_callback(data) == expected


def test_saved_keyboard() -> None:
    keyboard = saved_keyboard(Issue(5, "https://example/5", "x"))
    assert keyboard.inline_keyboard[0][0].callback_data == "done:5"
    assert keyboard.inline_keyboard[0][1].callback_data == "later:5"
    assert keyboard.inline_keyboard[0][2].url == "https://example/5"


