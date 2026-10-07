from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramBadRequest

from life_ops_bot.core import Capture, Issue
from life_ops_bot.github import GitHubError
from life_ops_bot.telegram import (
    CALLBACK_DATA_MAX_BYTES,
    MENU_DONE,
    MENU_GOALS,
    MENU_LATER,
    MENU_TASKS,
    NAVIGATION_ERROR,
    NavigationCallback,
    _handle_navigation_callback,
    _is_start,
    handle_callback,
    handle_message,
    main_menu_keyboard,
    parse_navigation_callback,
    render_goal,
    render_item,
    render_view,
)


def issue(
    number: int,
    *,
    title: str | None = None,
    labels: tuple[str, ...] = (),
    state: str = "open",
    body: str = "",
) -> Issue:
    return Issue(
        number,
        f"https://github.com/owner/tasks/issues/{number}",
        title or f"Issue {number}",
        labels,
        state,
        body,
    )


class FakeLifeOps:
    def __init__(self, issues: tuple[Issue, ...] = ()) -> None:
        self.issues = list(issues)
        self.captures: list[Capture] = []
        self.list_calls = 0
        self.get_calls: list[int] = []
        self.done_calls: list[int] = []
        self.later_calls: list[int] = []

    async def capture(self, capture: Capture) -> Issue:
        self.captures.append(capture)
        return issue(99)

    async def list_issues(self, *, state: str = "all") -> tuple[Issue, ...]:
        assert state == "all"
        self.list_calls += 1
        return tuple(self.issues)

    async def get_issue(self, issue_number: int) -> Issue:
        self.get_calls.append(issue_number)
        return next(item for item in self.issues if item.number == issue_number)

    async def done(self, issue_number: int) -> Issue:
        self.done_calls.append(issue_number)
        current = next(item for item in self.issues if item.number == issue_number)
        updated = Issue(
            current.number,
            current.url,
            current.title,
            current.labels,
            "closed",
            current.body,
        )
        self._replace(updated)
        return updated

    async def later(self, issue_number: int) -> Issue:
        self.later_calls.append(issue_number)
        current = next(item for item in self.issues if item.number == issue_number)
        labels = tuple(label for label in current.labels if not label.startswith("state:"))
        updated = Issue(
            current.number,
            current.url,
            current.title,
            (*labels, "state:later"),
            "open",
            current.body,
        )
        self._replace(updated)
        return updated

    def _replace(self, updated: Issue) -> None:
        self.issues = [updated if item.number == updated.number else item for item in self.issues]


def fake_message(
    *,
    user_id: int = 123,
    text: str | None = MENU_TASKS,
    forward_origin=None,
):
    return SimpleNamespace(
        from_user=SimpleNamespace(id=user_id),
        text=text,
        entities=None,
        chat=SimpleNamespace(id=user_id),
        message_id=7,
        forward_origin=forward_origin,
        answer=AsyncMock(),
    )


def fake_callback(*, data: str, user_id: int = 123):
    return SimpleNamespace(
        from_user=SimpleNamespace(id=user_id),
        data=data,
        answer=AsyncMock(),
        message=SimpleNamespace(edit_text=AsyncMock()),
    )


def test_main_menu_keyboard_exposes_all_views_without_typing_commands() -> None:
    keyboard = main_menu_keyboard()

    assert [[button.text for button in row] for row in keyboard.keyboard] == [
        [MENU_TASKS, MENU_GOALS],
        [MENU_LATER, MENU_DONE],
    ]
    assert keyboard.is_persistent is True
    assert keyboard.resize_keyboard is True


@pytest.mark.asyncio
async def test_start_shows_persistent_menu_without_github_or_capture() -> None:
    life_ops = FakeLifeOps((issue(1),))
    message = fake_message(text="/start")

    await handle_message(message, life_ops, 123)

    assert life_ops.captures == []
    assert life_ops.list_calls == 0
    message.answer.assert_awaited_once()
    reply = message.answer.await_args
    assert reply.args[0].startswith("Life Ops")
    assert reply.kwargs["reply_markup"].is_persistent is True


@pytest.mark.asyncio
async def test_menu_button_opens_view_instead_of_becoming_capture() -> None:
    later = issue(2, labels=("state:later",))
    life_ops = FakeLifeOps((issue(1), later))
    message = fake_message(text=MENU_LATER)

    await handle_message(message, life_ops, 123)

    assert life_ops.captures == []
    message.answer.assert_awaited_once()
    assert message.answer.await_args.args[0].startswith("🕓 Later — 1")


@pytest.mark.asyncio
async def test_unauthorized_menu_message_does_not_touch_navigation_or_capture() -> None:
    life_ops = FakeLifeOps((issue(1),))
    message = fake_message(user_id=999, text=MENU_TASKS)

    await handle_message(message, life_ops, 123)

    assert life_ops.list_calls == 0
    assert life_ops.captures == []
    message.answer.assert_not_awaited()


def test_tasks_goals_later_and_done_views_are_deterministic() -> None:
    parent = issue(10, title="Big plan", body="- [ ] #11 Child")
    child = issue(11, title="Child", body="Parent: #10")
    later = issue(12, labels=("state:later",))
    done = issue(13, state="closed")
    issues = (parent, child, later, done)

    tasks_text, tasks_markup = render_view(issues, "tasks", 0)
    goals_text, goals_markup = render_view(issues, "goals", 0)
    later_text, later_markup = render_view(issues, "later", 0)
    done_text, done_markup = render_view(issues, "done", 0)

    assert tasks_text.startswith("📋 Tasks — 1")
    assert tasks_markup.inline_keyboard[0][0].callback_data == "item:11:tasks:0"
    assert goals_text.startswith("🎯 Goals — 1")
    assert "· 0/1" in goals_markup.inline_keyboard[0][0].text
    assert later_text.startswith("🕓 Later — 1")
    assert later_markup.inline_keyboard[0][0].callback_data == "item:12:later:0"
    assert done_text.startswith("✅ Done — 1")
    assert done_markup.inline_keyboard[0][0].callback_data == "item:13:done:0"


def test_deferred_goal_is_only_in_later_not_active_goals() -> None:
    parent = issue(
        10,
        title="Deferred plan",
        labels=("state:later",),
        body="- [ ] #11 Child",
    )
    child = issue(11, title="Child", body="Parent: #10")
    issues = (parent, child)

    goals_text, goals_markup = render_view(issues, "goals", 0)
    later_text, later_markup = render_view(issues, "later", 0)

    assert goals_text == "🎯 Goals\nNo active goals."
    assert goals_markup is None
    assert later_text.startswith("🕓 Later — 1")
    assert later_markup.inline_keyboard[0][0].callback_data == "goal:10:later:0:0"


def test_deferred_open_goal_hides_redundant_later_action() -> None:
    parent = issue(
        10,
        title="Deferred plan",
        labels=("state:later",),
        body="- [ ] #11 Child",
    )
    child = issue(11, title="Child", body="Parent: #10")

    text, markup = render_goal(
        (parent, child),
        10,
        0,
        source_view="later",
    )

    assert "Status: 🕓 Later" in text
    action_texts = [button.text for button in markup.inline_keyboard[-2]]
    assert action_texts == ["Done", "GitHub"]


def test_view_paginates_and_clamps_out_of_range_page() -> None:
    issues = tuple(issue(number) for number in range(1, 10))

    text, markup = render_view(issues, "tasks", 99)

    assert "Page 2/2" in text
    assert markup.inline_keyboard[-1][0].callback_data == "nav:tasks:0"
    assert markup.inline_keyboard[-1][1].text == "2/2"


def test_empty_view_has_no_inline_keyboard() -> None:
    text, markup = render_view((), "done", 0)

    assert text == "✅ Done\nNothing completed yet."
    assert markup is None


def test_goal_detail_shows_progress_children_actions_and_back() -> None:
    parent = issue(10, title="Plan", body="- [ ] #11 Open\n- [x] #12 Closed")
    open_child = issue(11, title="Open", body="Parent: #10")
    closed_child = issue(12, title="Closed", state="closed")

    text, markup = render_goal((parent, open_child, closed_child), 10, 0)

    assert "Progress: 1/2 done · 1 remaining" in text
    assert markup.inline_keyboard[0][0].text.startswith("⬜ #11")
    assert markup.inline_keyboard[1][0].text.startswith("✅ #12")
    assert markup.inline_keyboard[-2][0].callback_data == "action:done:10:goal:goals:0:0"
    assert markup.inline_keyboard[-1][0].callback_data == "nav:goals:0"


def test_item_detail_reflects_status_and_returns_to_goal() -> None:
    current = issue(11, state="closed")

    text, markup = render_item(current, "g10", 2)

    assert "Status: ✅ Done" in text
    assert markup.inline_keyboard[0][0].callback_data == "action:later:11:g10:goals:0:2"
    assert markup.inline_keyboard[1][0].callback_data == "goal:10:goals:0:2"


@pytest.mark.asyncio
async def test_navigation_callback_opens_item_and_answers_callback() -> None:
    life_ops = FakeLifeOps((issue(11, title="Open me"),))
    callback = fake_callback(data="item:11:tasks:0")

    await handle_callback(callback, life_ops, 123)

    assert life_ops.get_calls == [11]
    callback.message.edit_text.assert_awaited_once()
    assert callback.message.edit_text.await_args.args[0].startswith("#11 Open me")
    callback.answer.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_navigation_done_action_updates_item_in_place() -> None:
    life_ops = FakeLifeOps((issue(11, title="Do it"),))
    callback = fake_callback(data="action:done:11:tasks:0")

    await handle_callback(callback, life_ops, 123)

    assert life_ops.done_calls == [11]
    assert "Status: ✅ Done" in callback.message.edit_text.await_args.args[0]
    callback.answer.assert_awaited_once_with("Done")


@pytest.mark.asyncio
async def test_goal_action_refreshes_goal_progress_view() -> None:
    parent = issue(10, title="Plan", body="- [ ] #11 Child")
    child = issue(11, title="Child", body="Parent: #10")
    life_ops = FakeLifeOps((parent, child))
    callback = fake_callback(data="action:later:10:goal:0")

    await handle_callback(callback, life_ops, 123)

    assert life_ops.later_calls == [10]
    assert life_ops.list_calls == 1
    assert callback.message.edit_text.await_args.args[0].startswith("🎯 #10 Plan")
    callback.answer.assert_awaited_once_with("Moved to Later")


@pytest.mark.asyncio
async def test_navigation_page_callback_renders_in_same_message() -> None:
    life_ops = FakeLifeOps(tuple(issue(number) for number in range(1, 10)))
    callback = fake_callback(data="nav:tasks:1")

    await handle_callback(callback, life_ops, 123)

    assert "Page 2/2" in callback.message.edit_text.await_args.args[0]
    callback.answer.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_noop_callback_only_acknowledges() -> None:
    life_ops = FakeLifeOps()
    callback = fake_callback(data="noop")

    await handle_callback(callback, life_ops, 123)

    callback.message.edit_text.assert_not_awaited()
    callback.answer.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_unauthorized_navigation_callback_has_no_side_effects() -> None:
    life_ops = FakeLifeOps((issue(1),))
    callback = fake_callback(data="nav:tasks:0", user_id=999)

    await handle_callback(callback, life_ops, 123)

    assert life_ops.list_calls == 0
    callback.message.edit_text.assert_not_awaited()
    callback.answer.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("menu_text", [MENU_TASKS, MENU_GOALS, MENU_LATER, MENU_DONE])
async def test_forwarded_menu_label_text_stays_on_capture_path(menu_text: str) -> None:
    life_ops = FakeLifeOps()
    message = fake_message(
        text=menu_text,
        forward_origin=SimpleNamespace(),
    )

    await handle_message(message, life_ops, 123)

    assert len(life_ops.captures) == 1
    assert life_ops.captures[0].text == menu_text
    assert life_ops.list_calls == 0
    assert message.answer.await_count == 1
    assert message.answer.await_args.args[0].startswith("✅ Saved #99")


@pytest.mark.asyncio
async def test_forwarded_start_text_stays_on_capture_path() -> None:
    life_ops = FakeLifeOps()
    message = fake_message(
        text="/start this is forwarded content",
        forward_origin=SimpleNamespace(),
    )

    await handle_message(message, life_ops, 123)

    assert len(life_ops.captures) == 1
    assert life_ops.captures[0].text == "/start this is forwarded content"
    assert message.answer.await_count == 1
    assert message.answer.await_args.args[0].startswith("✅ Saved #99")


@pytest.mark.asyncio
async def test_start_does_not_touch_github_even_in_webhook_mode() -> None:
    message = fake_message(text="/start")
    life_ops = FailingLifeOps(retryable=True)

    await handle_message(
        message,
        life_ops,
        123,
        propagate_github_errors=True,
    )

    message.answer.assert_awaited_once()


def test_goal_open_preserves_source_goals_page_separately_from_children_page() -> None:
    parents = tuple(
        issue(
            number,
            title=f"Goal {number}",
            body=f"- [ ] #{number + 100} Child",
        )
        for number in range(1, 10)
    )
    children = tuple(
        issue(number + 100, title=f"Child {number}", body=f"Parent: #{number}")
        for number in range(1, 10)
    )

    _, goals_markup = render_view((*parents, *children), "goals", 1)
    goal_button = goals_markup.inline_keyboard[0][0]

    assert goal_button.callback_data == "goal:9:goals:1:0"

    _, goal_markup = render_goal(
        (*parents, *children),
        9,
        0,
        source_page=1,
    )
    assert goal_markup.inline_keyboard[-1][0].callback_data == "nav:goals:1"


def test_nested_child_goal_opens_goal_detail_and_backs_to_parent_detail() -> None:
    root = issue(10, title="Root", body="- [ ] #11 Nested")
    nested = issue(
        11,
        title="Nested",
        body="Parent: #10\n\n- [ ] #12 Leaf",
    )
    leaf = issue(12, title="Leaf", body="Parent: #11")
    issues = (root, nested, leaf)

    _, root_markup = render_goal(issues, 10, 0)

    assert root_markup.inline_keyboard[0][0].callback_data == (
        "goal:11:goals:0:0:10.0"
    )

    _, nested_markup = render_goal(
        issues,
        11,
        0,
        trail=((10, 0),),
    )

    assert nested_markup.inline_keyboard[0][0].callback_data == (
        "item:12:g11:goals:0:0:10.0"
    )
    assert nested_markup.inline_keyboard[-1][0].callback_data == (
        "goal:10:goals:0:0"
    )


def test_nested_goal_item_round_trip_preserves_breadcrumb() -> None:
    current = issue(12, title="Leaf")

    _, markup = render_item(
        current,
        "g11",
        0,
        trail=((10, 0),),
    )

    assert markup.inline_keyboard[0][0].callback_data == (
        "action:done:12:g11:goals:0:0:10.0"
    )
    assert markup.inline_keyboard[1][0].callback_data == (
        "goal:11:goals:0:0:10.0"
    )


def test_completed_goal_in_done_opens_goal_detail_and_returns_to_done() -> None:
    parent = issue(10, title="Finished plan", state="closed", body="- [x] #11 Child")
    child = issue(11, title="Finished child", state="closed", body="Parent: #10")

    _, done_markup = render_view((parent, child), "done", 0)

    assert done_markup.inline_keyboard[0][0].callback_data == "goal:10:done:0:0"

    _, goal_markup = render_goal(
        (parent, child),
        10,
        0,
        source_view="done",
        source_page=0,
    )

    assert goal_markup.inline_keyboard[0][0].callback_data == "item:11:g10:done:0:0"
    assert goal_markup.inline_keyboard[-1][0].callback_data == "nav:done:0"


def test_completed_goal_child_returns_to_done_backed_goal_detail() -> None:
    current = issue(11, title="Finished child", state="closed")

    _, markup = render_item(
        current,
        "g10",
        0,
        source_view="done",
        source_page=2,
    )

    assert markup.inline_keyboard[0][0].callback_data == (
        "action:later:11:g10:done:2:0"
    )
    assert markup.inline_keyboard[1][0].callback_data == "goal:10:done:2:0"


def test_goal_child_pagination_preserves_source_goals_page() -> None:
    parent = issue(
        10,
        title="Plan",
        body="\n".join(f"- [ ] #{number} Child" for number in range(11, 21)),
    )
    children = tuple(issue(number) for number in range(11, 21))

    _, markup = render_goal((parent, *children), 10, 0, source_page=3)

    assert markup.inline_keyboard[8][1].callback_data == "goal:10:goals:3:1"
    assert markup.inline_keyboard[-1][0].callback_data == "nav:goals:3"


def test_deep_goal_breadcrumb_callbacks_stay_within_telegram_limit() -> None:
    parent = issue(9999999, title="Deep goal", body="- [ ] #8888888 Child")
    child = issue(8888888, title="Leaf", body="Parent: #9999999")
    deep_trail = (
        (1111111, 99),
        (2222222, 99),
        (3333333, 99),
        (4444444, 99),
        (5555555, 99),
    )

    _, markup = render_goal(
        (parent, child),
        9999999,
        0,
        source_view="goals",
        source_page=99,
        trail=deep_trail,
    )

    callback_data = [
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
        if button.callback_data is not None
    ]
    assert callback_data
    assert all(
        len(data.encode("utf-8")) <= CALLBACK_DATA_MAX_BYTES for data in callback_data
    )
    assert any(data.startswith("goal:4444444") or "5555555.99" in data for data in callback_data)


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ("nav:tasks:0", NavigationCallback(kind="nav", view="tasks", page=0)),
        ("goal:18:2", NavigationCallback(kind="goal", issue_number=18, page=2)),
        (
            "goal:18:3:2",
            NavigationCallback(kind="goal", issue_number=18, page=2, source_page=3),
        ),
        (
            "goal:18:done:3:2",
            NavigationCallback(
                kind="goal",
                issue_number=18,
                page=2,
                source_page=3,
                source_view="done",
            ),
        ),
        (
            "goal:18:done:3:2:10.0,11.1",
            NavigationCallback(
                kind="goal",
                issue_number=18,
                page=2,
                source_page=3,
                source_view="done",
                trail=((10, 0), (11, 1)),
            ),
        ),
        (
            "item:22:g18:done:3:1",
            NavigationCallback(
                kind="item",
                issue_number=22,
                view="g18",
                page=1,
                source_page=3,
                source_view="done",
            ),
        ),
        (
            "action:later:22:g18:done:3:1",
            NavigationCallback(
                kind="action",
                issue_number=22,
                view="g18",
                action="later",
                page=1,
                source_page=3,
                source_view="done",
            ),
        ),
        (
            "action:later:22:g18:done:3:1:10.0",
            NavigationCallback(
                kind="action",
                issue_number=22,
                view="g18",
                action="later",
                page=1,
                source_page=3,
                source_view="done",
                trail=((10, 0),),
            ),
        ),
        (
            "item:22:g18:3:1",
            NavigationCallback(
                kind="item",
                issue_number=22,
                view="g18",
                page=1,
                source_page=3,
            ),
        ),
        (
            "action:done:22:goal:3:1",
            NavigationCallback(
                kind="action",
                issue_number=22,
                view="goal",
                action="done",
                page=1,
                source_page=3,
            ),
        ),
        (
            "item:22:g18:1",
            NavigationCallback(kind="item", issue_number=22, view="g18", page=1),
        ),
        (
            "action:done:22:tasks:0",
            NavigationCallback(
                kind="action",
                issue_number=22,
                view="tasks",
                action="done",
                page=0,
            ),
        ),
        ("noop", NavigationCallback(kind="noop")),
        ("nav:unknown:0", None),
        ("item:0:tasks:0", None),
        ("item:2:bad:0", None),
        ("goal:2:-1", None),
        ("action:nope:2:tasks:0", None),
        ("action:done:x:tasks:0", None),
        ("goal:2:goals:0:0:bad", None),
        ("goal:2:goals:0:0:0.0", None),
        (None, None),
    ],
)
def test_parse_navigation_callback(data, expected) -> None:
    assert parse_navigation_callback(data) == expected


class FailingLifeOps(FakeLifeOps):
    def __init__(self, *, retryable: bool) -> None:
        super().__init__()
        self.retryable = retryable

    async def list_issues(self, *, state: str = "all") -> tuple[Issue, ...]:
        raise GitHubError("failed", retryable=self.retryable)


@pytest.mark.asyncio
async def test_menu_navigation_failure_is_user_facing_when_permanent() -> None:
    message = fake_message(text=MENU_TASKS)

    await handle_message(message, FailingLifeOps(retryable=False), 123)

    message.answer.assert_awaited_once_with(NAVIGATION_ERROR)


@pytest.mark.asyncio
async def test_menu_navigation_retryable_failure_propagates_in_webhook_mode() -> None:
    message = fake_message(text=MENU_TASKS)

    with pytest.raises(GitHubError, match="failed"):
        await handle_message(
            message,
            FailingLifeOps(retryable=True),
            123,
            propagate_github_errors=True,
        )

    message.answer.assert_not_awaited()


@pytest.mark.asyncio
async def test_goal_callback_opens_goal_detail() -> None:
    parent = issue(10, title="Plan", body="- [ ] #11 Child")
    child = issue(11, title="Child", body="Parent: #10")
    life_ops = FakeLifeOps((parent, child))
    callback = fake_callback(data="goal:10:0")

    await handle_callback(callback, life_ops, 123)

    assert life_ops.list_calls == 1
    assert callback.message.edit_text.await_args.args[0].startswith("🎯 #10 Plan")
    callback.answer.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_navigation_permanent_github_failure_is_alerted() -> None:
    callback = fake_callback(data="nav:tasks:0")

    await handle_callback(callback, FailingLifeOps(retryable=False), 123)

    callback.answer.assert_awaited_once_with(NAVIGATION_ERROR, show_alert=True)
    callback.message.edit_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_navigation_retryable_github_failure_propagates_for_webhook_retry() -> None:
    callback = fake_callback(data="nav:tasks:0")

    with pytest.raises(GitHubError, match="failed"):
        await handle_callback(
            callback,
            FailingLifeOps(retryable=True),
            123,
            propagate_github_errors=True,
        )

    callback.answer.assert_not_awaited()
    callback.message.edit_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_navigation_callback_without_editable_message_reports_error() -> None:
    life_ops = FakeLifeOps((issue(1),))
    callback = fake_callback(data="nav:tasks:0")
    callback.message = None

    await handle_callback(callback, life_ops, 123)

    callback.answer.assert_awaited_once_with(NAVIGATION_ERROR, show_alert=True)


@pytest.mark.asyncio
async def test_navigation_edit_bad_request_reports_error() -> None:
    life_ops = FakeLifeOps((issue(1),))
    callback = fake_callback(data="nav:tasks:0")
    callback.message.edit_text.side_effect = TelegramBadRequest(
        method=SimpleNamespace(),
        message="message can't be edited",
    )

    await handle_callback(callback, life_ops, 123)

    callback.answer.assert_awaited_once_with(NAVIGATION_ERROR, show_alert=True)


@pytest.mark.asyncio
async def test_navigation_not_modified_retry_is_treated_as_success() -> None:
    life_ops = FakeLifeOps((issue(1),))
    callback = fake_callback(data="nav:tasks:0")
    callback.message.edit_text.side_effect = TelegramBadRequest(
        method=SimpleNamespace(),
        message="message is not modified",
    )

    await handle_callback(callback, life_ops, 123)

    callback.answer.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_invalid_internal_navigation_shape_is_rejected() -> None:
    life_ops = FakeLifeOps()
    callback = fake_callback(data="noop")

    await _handle_navigation_callback(
        callback,
        life_ops,
        NavigationCallback(kind="invalid"),
        propagate_github_errors=False,
    )

    callback.answer.assert_awaited_once_with(
        "❌ Couldn't update this item. Please try again.",
        show_alert=True,
    )


def test_goal_detail_paginates_children_in_both_directions_and_closed_goal() -> None:
    parent = issue(
        10,
        title="Plan",
        state="closed",
        body="\n".join(f"- [ ] #{number} Child" for number in range(11, 21)),
    )
    children = tuple(issue(number) for number in range(11, 21))

    first_text, first_markup = render_goal((parent, *children), 10, 0)
    second_text, second_markup = render_goal((parent, *children), 10, 1)

    assert "Status: ✅ Done" in first_text
    assert first_markup.inline_keyboard[8][0].text == "1/2"
    assert first_markup.inline_keyboard[8][1].callback_data == "goal:10:goals:0:1"
    assert "Page" not in second_text
    assert second_markup.inline_keyboard[2][0].callback_data == "goal:10:goals:0:0"
    action_texts = [button.text for button in second_markup.inline_keyboard[-2]]
    assert "Done" not in action_texts


def test_goal_detail_rejects_missing_goal_or_children() -> None:
    with pytest.raises(GitHubError, match="no longer available"):
        render_goal((issue(1),), 1, 0)

    with pytest.raises(GitHubError, match="no longer available"):
        render_goal((issue(2, body="- [ ] #1 Child"), issue(1)), 999, 0)


def test_render_item_covers_later_view_and_fallback_back_context() -> None:
    later = issue(4, labels=("state:later",))

    text, markup = render_item(later, "later", 0)
    assert "Status: 🕓 Later" in text
    assert [button.text for button in markup.inline_keyboard[0]] == ["Done", "GitHub"]
    assert markup.inline_keyboard[1][0].callback_data == "nav:later:0"

    _, fallback = render_item(issue(5), "unknown", 0)
    assert fallback.inline_keyboard[1][0].callback_data == "nav:tasks:0"


def test_status_icons_and_long_titles_are_visible_in_task_list() -> None:
    issues = (
        issue(1, title="A " * 40, labels=("state:waiting",)),
        issue(2, labels=("state:now",)),
        issue(3, labels=("state:inbox",)),
    )

    _, markup = render_view(issues, "tasks", 0)

    labels = [row[0].text for row in markup.inline_keyboard]
    assert labels[0].startswith("⏳ #1")
    assert labels[0].endswith("…")
    assert labels[1].startswith("🔥 #2")
    assert labels[2].startswith("📥 #3")


def test_first_page_pagination_has_next_control() -> None:
    issues = tuple(issue(number) for number in range(1, 10))

    _, markup = render_view(issues, "tasks", 0)

    assert markup.inline_keyboard[-1][0].text == "1/2"
    assert markup.inline_keyboard[-1][1].callback_data == "nav:tasks:1"


def test_render_view_rejects_unknown_view() -> None:
    with pytest.raises(ValueError, match="unknown navigation view"):
        render_view((), "wat", 0)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("/start", True),
        ("/start payload", True),
        ("/start@life_ops_bot", True),
        ("", False),
        ("hello", False),
    ],
)
def test_is_start(text, expected) -> None:
    assert _is_start(text) is expected
