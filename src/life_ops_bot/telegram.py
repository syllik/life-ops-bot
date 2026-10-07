from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    MessageOriginChannel,
    MessageOriginChat,
    MessageOriginHiddenUser,
    MessageOriginUser,
    ReplyKeyboardMarkup,
)

from .core import Capture, Issue, LifeOps, goal_children
from .github import GitHubError

SAVE_ERROR = "❌ Couldn't save this item. Please try again."
ACTION_ERROR = "❌ Couldn't update this item. Please try again."
NAVIGATION_ERROR = "❌ Couldn't load Life Ops. Please try again."

MENU_TASKS = "📋 Tasks"
MENU_GOALS = "🎯 Goals"
MENU_LATER = "🕓 Later"
MENU_DONE = "✅ Done"
PAGE_SIZE = 8
VIEW_LABELS = {
    "tasks": "📋 Tasks",
    "goals": "🎯 Goals",
    "later": "🕓 Later",
    "done": "✅ Done",
}
MENU_VIEWS = {
    MENU_TASKS: "tasks",
    MENU_GOALS: "goals",
    MENU_LATER: "later",
    MENU_DONE: "done",
}


@dataclass(frozen=True, slots=True)
class NavigationCallback:
    kind: str
    page: int = 0
    source_page: int = 0
    source_view: str = "goals"
    trail: tuple[tuple[int, int], ...] = ()
    issue_number: int | None = None
    view: str | None = None
    action: str | None = None


def build_router(
    life_ops: LifeOps,
    allowed_user_id: int,
    *,
    propagate_github_errors: bool = False,
) -> Router:
    router = Router(name="life-ops")

    @router.message()
    async def capture_message(message: Message) -> None:
        await handle_message(
            message,
            life_ops,
            allowed_user_id,
            propagate_github_errors=propagate_github_errors,
        )

    @router.callback_query()
    async def issue_callback(callback: CallbackQuery) -> None:
        await handle_callback(
            callback,
            life_ops,
            allowed_user_id,
            propagate_github_errors=propagate_github_errors,
        )

    return router


async def handle_message(
    message: Message,
    life_ops: LifeOps,
    allowed_user_id: int,
    *,
    propagate_github_errors: bool = False,
) -> None:
    sender = message.from_user
    if sender is None or sender.id != allowed_user_id:
        return

    text = message.text
    if text is None:
        return

    if message.forward_origin is None and _is_start(text):
        await message.answer(
            "Life Ops\nUse the buttons below instead of commands.",
            reply_markup=main_menu_keyboard(),
        )
        return

    view = MENU_VIEWS.get(text) if message.forward_origin is None else None
    if view is not None:
        await _send_view(
            message,
            life_ops,
            view,
            0,
            propagate_github_errors=propagate_github_errors,
        )
        return

    capture = Capture(
        text=text,
        chat_id=message.chat.id,
        message_id=message.message_id,
        forwarded_from=describe_forward_origin(message),
        link_targets=text_link_targets(message),
    )
    try:
        issue = await life_ops.capture(capture)
    except GitHubError as exc:
        if propagate_github_errors and exc.retryable:
            raise
        await message.answer(SAVE_ERROR)
        return

    await message.answer(
        f"✅ Saved #{issue.number}\n{issue.url}",
        reply_markup=saved_keyboard(issue),
        disable_web_page_preview=True,
    )


async def handle_callback(
    callback: CallbackQuery,
    life_ops: LifeOps,
    allowed_user_id: int,
    *,
    propagate_github_errors: bool = False,
) -> None:
    sender = callback.from_user
    if sender.id != allowed_user_id:
        return

    navigation = parse_navigation_callback(callback.data)
    if navigation is not None:
        await _handle_navigation_callback(
            callback,
            life_ops,
            navigation,
            propagate_github_errors=propagate_github_errors,
        )
        return

    parsed = parse_callback(callback.data)
    if parsed is None:
        await _answer_callback(callback, ACTION_ERROR, show_alert=True)
        return

    action, issue_number = parsed
    operation: Callable[[int], Awaitable[Issue]] = (
        life_ops.done if action == "done" else life_ops.later
    )
    try:
        await operation(issue_number)
    except GitHubError as exc:
        if propagate_github_errors and exc.retryable:
            raise
        await _answer_callback(callback, ACTION_ERROR, show_alert=True)
        return

    await _answer_callback(
        callback,
        "Done" if action == "done" else "Moved to Later",
    )


async def _handle_navigation_callback(
    callback: CallbackQuery,
    life_ops: LifeOps,
    navigation: NavigationCallback,
    *,
    propagate_github_errors: bool,
) -> None:
    if navigation.kind == "noop":
        await _answer_callback(callback)
        return

    try:
        if navigation.kind == "nav" and navigation.view is not None:
            issues = await life_ops.list_issues()
            text, markup = render_view(issues, navigation.view, navigation.page)
        elif navigation.kind == "goal" and navigation.issue_number is not None:
            issues = await life_ops.list_issues()
            text, markup = render_goal(
                issues,
                navigation.issue_number,
                navigation.page,
                source_page=navigation.source_page,
                source_view=navigation.source_view,
                trail=navigation.trail,
            )
        elif (
            navigation.kind == "item"
            and navigation.issue_number is not None
            and navigation.view is not None
        ):
            issue = await life_ops.get_issue(navigation.issue_number)
            text, markup = render_item(
                issue,
                navigation.view,
                navigation.page,
                source_page=navigation.source_page,
                source_view=navigation.source_view,
                trail=navigation.trail,
            )
        elif (
            navigation.kind == "action"
            and navigation.issue_number is not None
            and navigation.view is not None
            and navigation.action is not None
        ):
            operation: Callable[[int], Awaitable[Issue]] = (
                life_ops.done if navigation.action == "done" else life_ops.later
            )
            issue = await operation(navigation.issue_number)
            if navigation.view == "goal":
                issues = await life_ops.list_issues()
                text, markup = render_goal(
                    issues,
                    issue.number,
                    navigation.page,
                    source_page=navigation.source_page,
                    source_view=navigation.source_view,
                    trail=navigation.trail,
                )
            else:
                text, markup = render_item(
                    issue,
                    navigation.view,
                    navigation.page,
                    source_page=navigation.source_page,
                    source_view=navigation.source_view,
                    trail=navigation.trail,
                )
        else:
            await _answer_callback(callback, ACTION_ERROR, show_alert=True)
            return
    except GitHubError as exc:
        if propagate_github_errors and exc.retryable:
            raise
        await _answer_callback(callback, NAVIGATION_ERROR, show_alert=True)
        return

    if not await _edit_callback(callback, text, markup):
        return

    if navigation.kind == "action":
        await _answer_callback(
            callback,
            "Done" if navigation.action == "done" else "Moved to Later",
        )
    else:
        await _answer_callback(callback)


async def _send_view(
    message: Message,
    life_ops: LifeOps,
    view: str,
    page: int,
    *,
    propagate_github_errors: bool,
) -> None:
    try:
        issues = await life_ops.list_issues()
    except GitHubError as exc:
        if propagate_github_errors and exc.retryable:
            raise
        await message.answer(NAVIGATION_ERROR)
        return

    text, markup = render_view(issues, view, page)
    await message.answer(
        text,
        reply_markup=markup,
        disable_web_page_preview=True,
    )


async def _edit_callback(
    callback: CallbackQuery,
    text: str,
    markup: InlineKeyboardMarkup | None,
) -> bool:
    message = callback.message
    if message is None or not hasattr(message, "edit_text"):
        await _answer_callback(callback, NAVIGATION_ERROR, show_alert=True)
        return False
    try:
        await message.edit_text(
            text,
            reply_markup=markup,
            disable_web_page_preview=True,
        )
    except TelegramBadRequest:
        await _answer_callback(callback, NAVIGATION_ERROR, show_alert=True)
        return False
    return True


async def _answer_callback(
    callback: CallbackQuery,
    text: str | None = None,
    *,
    show_alert: bool = False,
) -> None:
    try:
        if show_alert and text is not None:
            await callback.answer(text, show_alert=True)
        elif text is None:
            await callback.answer()
        else:
            await callback.answer(text)
    except TelegramBadRequest:
        # Callback answers are time-limited by Telegram. A 400 cannot be repaired by
        # redelivering the immutable callback, while network/5xx errors still propagate.
        return


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=MENU_TASKS), KeyboardButton(text=MENU_GOALS)],
            [KeyboardButton(text=MENU_LATER), KeyboardButton(text=MENU_DONE)],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Capture something or choose a view",
    )


def saved_keyboard(issue: Issue) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Done", callback_data=f"done:{issue.number}"),
                InlineKeyboardButton(text="Later", callback_data=f"later:{issue.number}"),
                InlineKeyboardButton(text="GitHub", url=issue.url),
            ]
        ]
    )


def parse_callback(data: str | None) -> tuple[str, int] | None:
    if data is None:
        return None
    action, separator, raw_number = data.partition(":")
    if separator != ":" or action not in {"done", "later"}:
        return None
    try:
        issue_number = int(raw_number)
    except ValueError:
        return None
    if issue_number <= 0:
        return None
    return action, issue_number


def render_view(
    issues: tuple[Issue, ...],
    view: str,
    page: int,
) -> tuple[str, InlineKeyboardMarkup | None]:
    if view not in VIEW_LABELS:
        raise ValueError("unknown navigation view")

    relations = goal_children(issues)
    goal_numbers = set(relations)
    if view == "tasks":
        items = [
            issue
            for issue in issues
            if issue.state == "open"
            and issue.number not in goal_numbers
            and "state:later" not in issue.labels
        ]
        empty_text = "No active tasks."
    elif view == "goals":
        items = [
            issue
            for issue in issues
            if issue.state == "open"
            and issue.number in goal_numbers
            and "state:later" not in issue.labels
        ]
        empty_text = "No active goals."
    elif view == "later":
        items = [
            issue
            for issue in issues
            if issue.state == "open" and "state:later" in issue.labels
        ]
        empty_text = "Nothing in Later."
    else:
        items = [issue for issue in issues if issue.state == "closed"]
        empty_text = "Nothing completed yet."

    page_items, current_page, page_count = _page(items, page)
    title = VIEW_LABELS[view]
    if not items:
        return f"{title}\n{empty_text}", None

    text = f"{title} — {len(items)}\nPage {current_page + 1}/{page_count}\nTap an item to open."
    rows: list[list[InlineKeyboardButton]] = []
    for issue in page_items:
        if issue.number in goal_numbers:
            children = relations[issue.number]
            done = sum(child.state == "closed" for child in children)
            label = f"🎯 #{issue.number} {_short_title(issue.title, 34)} · {done}/{len(children)}"
            callback_data = _goal_callback_data(
                issue.number,
                view,
                current_page,
                0,
                (),
            )
        else:
            icon = _status_icon(issue)
            label = f"{icon} #{issue.number} {_short_title(issue.title, 45)}"
            callback_data = f"item:{issue.number}:{view}:{current_page}"
        rows.append([InlineKeyboardButton(text=label, callback_data=callback_data)])

    pagination = _pagination_row(view, current_page, page_count)
    if pagination:
        rows.append(pagination)
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


def render_goal(
    issues: tuple[Issue, ...],
    goal_number: int,
    page: int,
    *,
    source_page: int = 0,
    source_view: str = "goals",
    trail: tuple[tuple[int, int], ...] = (),
) -> tuple[str, InlineKeyboardMarkup]:
    by_number = {issue.number: issue for issue in issues}
    goal = by_number.get(goal_number)
    relations = goal_children(issues)
    children = list(relations.get(goal_number, ()))
    if goal is None or not children:
        raise GitHubError("Goal is no longer available")

    done = sum(child.state == "closed" for child in children)
    remaining = len(children) - done
    status = "✅ Done" if goal.state == "closed" else "🎯 Active"
    page_items, current_page, page_count = _page(children, page)
    text = (
        f"🎯 #{goal.number} {goal.title}\n"
        f"Status: {status}\n"
        f"Progress: {done}/{len(children)} done · {remaining} remaining"
    )

    rows: list[list[InlineKeyboardButton]] = []
    for child in page_items:
        if child.number in relations:
            nested_children = relations[child.number]
            nested_done = sum(item.state == "closed" for item in nested_children)
            label = (
                f"🎯 #{child.number} {_short_title(child.title, 34)} · "
                f"{nested_done}/{len(nested_children)}"
            )
            callback_data = _goal_callback_data(
                child.number,
                source_view,
                source_page,
                0,
                (*trail, (goal.number, current_page)),
            )
        else:
            label = f"{_status_icon(child)} #{child.number} {_short_title(child.title, 43)}"
            callback_data = _item_callback_data(
                child.number,
                f"g{goal.number}",
                source_view,
                source_page,
                current_page,
                trail,
            )
        rows.append([InlineKeyboardButton(text=label, callback_data=callback_data)])

    if page_count > 1:
        row: list[InlineKeyboardButton] = []
        if current_page > 0:
            row.append(
                InlineKeyboardButton(
                    text="◀️",
                    callback_data=_goal_callback_data(
                        goal.number,
                        source_view,
                        source_page,
                        current_page - 1,
                        trail,
                    ),
                )
            )
        row.append(
            InlineKeyboardButton(
                text=f"{current_page + 1}/{page_count}",
                callback_data="noop",
            )
        )
        if current_page + 1 < page_count:
            row.append(
                InlineKeyboardButton(
                    text="▶️",
                    callback_data=_goal_callback_data(
                        goal.number,
                        source_view,
                        source_page,
                        current_page + 1,
                        trail,
                    ),
                )
            )
        rows.append(row)

    action_row: list[InlineKeyboardButton] = []
    if goal.state != "closed":
        action_row.append(
            InlineKeyboardButton(
                text="Done",
                callback_data=_action_callback_data(
                    "done",
                    goal.number,
                    "goal",
                    current_page,
                    source_page,
                    source_view,
                    trail,
                ),
            )
        )
    if "state:later" not in goal.labels or goal.state == "closed":
        action_row.append(
            InlineKeyboardButton(
                text="Later",
                callback_data=_action_callback_data(
                    "later",
                    goal.number,
                    "goal",
                    current_page,
                    source_page,
                    source_view,
                    trail,
                ),
            )
        )
    action_row.append(InlineKeyboardButton(text="GitHub", url=goal.url))
    rows.append(action_row)
    if trail:
        parent_goal_number, parent_page = trail[-1]
        back_data = _goal_callback_data(
            parent_goal_number,
            source_view,
            source_page,
            parent_page,
            trail[:-1],
        )
    else:
        back_data = f"nav:{source_view}:{source_page}"
    rows.append([InlineKeyboardButton(text="← Back", callback_data=back_data)])
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


def render_item(
    issue: Issue,
    context: str,
    page: int,
    *,
    source_page: int = 0,
    source_view: str = "goals",
    trail: tuple[tuple[int, int], ...] = (),
) -> tuple[str, InlineKeyboardMarkup]:
    if issue.state == "closed":
        status = "✅ Done"
    elif "state:later" in issue.labels:
        status = "🕓 Later"
    else:
        status = "⬜ Active"

    text = f"#{issue.number} {issue.title}\nStatus: {status}"
    action_row: list[InlineKeyboardButton] = []
    if issue.state != "closed":
        action_row.append(
            InlineKeyboardButton(
                text="Done",
                callback_data=_action_callback_data(
                    "done",
                    issue.number,
                    context,
                    page,
                    source_page,
                    source_view,
                    trail,
                ),
            )
        )
    if "state:later" not in issue.labels or issue.state == "closed":
        action_row.append(
            InlineKeyboardButton(
                text="Later",
                callback_data=_action_callback_data(
                    "later",
                    issue.number,
                    context,
                    page,
                    source_page,
                    source_view,
                    trail,
                ),
            )
        )
    action_row.append(InlineKeyboardButton(text="GitHub", url=issue.url))

    if context.startswith("g") and context[1:].isdigit():
        back_data = _goal_callback_data(
            int(context[1:]),
            source_view,
            source_page,
            page,
            trail,
        )
    elif context in VIEW_LABELS:
        back_data = f"nav:{context}:{page}"
    else:
        back_data = "nav:tasks:0"

    return text, InlineKeyboardMarkup(
        inline_keyboard=[
            action_row,
            [InlineKeyboardButton(text="← Back", callback_data=back_data)],
        ]
    )


def parse_navigation_callback(data: str | None) -> NavigationCallback | None:
    if data == "noop":
        return NavigationCallback(kind="noop")
    if data is None:
        return None

    parts = data.split(":")
    try:
        if len(parts) == 3 and parts[0] == "nav" and parts[1] in VIEW_LABELS:
            page = int(parts[2])
            return _navigation_callback(kind="nav", view=parts[1], page=page)
        if len(parts) in {5, 6} and parts[0] == "goal" and parts[2] in VIEW_LABELS:
            issue_number = int(parts[1])
            source_page = int(parts[3])
            page = int(parts[4])
            trail = _parse_trail(parts[5]) if len(parts) == 6 else ()
            return _navigation_callback(
                kind="goal",
                issue_number=issue_number,
                page=page,
                source_page=source_page,
                source_view=parts[2],
                trail=trail,
            )
        if len(parts) == 4 and parts[0] == "goal":
            issue_number = int(parts[1])
            source_page = int(parts[2])
            page = int(parts[3])
            return _navigation_callback(
                kind="goal",
                issue_number=issue_number,
                page=page,
                source_page=source_page,
            )
        if len(parts) == 3 and parts[0] == "goal":
            issue_number = int(parts[1])
            page = int(parts[2])
            return _navigation_callback(kind="goal", issue_number=issue_number, page=page)
        if len(parts) in {6, 7} and parts[0] == "item" and parts[3] in VIEW_LABELS:
            issue_number = int(parts[1])
            source_page = int(parts[4])
            page = int(parts[5])
            trail = _parse_trail(parts[6]) if len(parts) == 7 else ()
            return _navigation_callback(
                kind="item",
                issue_number=issue_number,
                view=parts[2],
                page=page,
                source_page=source_page,
                source_view=parts[3],
                trail=trail,
            )
        if len(parts) == 5 and parts[0] == "item":
            issue_number = int(parts[1])
            source_page = int(parts[3])
            page = int(parts[4])
            return _navigation_callback(
                kind="item",
                issue_number=issue_number,
                view=parts[2],
                page=page,
                source_page=source_page,
            )
        if len(parts) == 4 and parts[0] == "item":
            issue_number = int(parts[1])
            page = int(parts[3])
            return _navigation_callback(
                kind="item",
                issue_number=issue_number,
                view=parts[2],
                page=page,
            )
        if (
            len(parts) in {7, 8}
            and parts[0] == "action"
            and parts[1] in {"done", "later"}
            and parts[4] in VIEW_LABELS
        ):
            issue_number = int(parts[2])
            source_page = int(parts[5])
            page = int(parts[6])
            trail = _parse_trail(parts[7]) if len(parts) == 8 else ()
            return _navigation_callback(
                kind="action",
                issue_number=issue_number,
                view=parts[3],
                action=parts[1],
                page=page,
                source_page=source_page,
                source_view=parts[4],
                trail=trail,
            )
        if (
            len(parts) == 6
            and parts[0] == "action"
            and parts[1] in {"done", "later"}
        ):
            issue_number = int(parts[2])
            source_page = int(parts[4])
            page = int(parts[5])
            return _navigation_callback(
                kind="action",
                issue_number=issue_number,
                view=parts[3],
                action=parts[1],
                page=page,
                source_page=source_page,
            )
        if (
            len(parts) == 5
            and parts[0] == "action"
            and parts[1] in {"done", "later"}
        ):
            issue_number = int(parts[2])
            page = int(parts[4])
            return _navigation_callback(
                kind="action",
                issue_number=issue_number,
                view=parts[3],
                action=parts[1],
                page=page,
            )
    except ValueError:
        return None
    return None


def _navigation_callback(
    *,
    kind: str,
    page: int,
    source_page: int = 0,
    source_view: str = "goals",
    trail: tuple[tuple[int, int], ...] = (),
    issue_number: int | None = None,
    view: str | None = None,
    action: str | None = None,
) -> NavigationCallback | None:
    if (
        page < 0
        or source_page < 0
        or source_view not in VIEW_LABELS
        or (issue_number is not None and issue_number <= 0)
    ):
        return None
    if kind in {"item", "action"} and view is not None:
        if view not in VIEW_LABELS and view != "goal" and not (
            view.startswith("g") and view[1:].isdigit() and int(view[1:]) > 0
        ):
            return None
    return NavigationCallback(
        kind=kind,
        page=page,
        source_page=source_page,
        source_view=source_view,
        trail=trail,
        issue_number=issue_number,
        view=view,
        action=action,
    )


def _goal_callback_data(
    goal_number: int,
    source_view: str,
    source_page: int,
    page: int,
    trail: tuple[tuple[int, int], ...],
) -> str:
    base = f"goal:{goal_number}:{source_view}:{source_page}:{page}"
    return _with_trail(base, trail)


def _item_callback_data(
    issue_number: int,
    context: str,
    source_view: str,
    source_page: int,
    page: int,
    trail: tuple[tuple[int, int], ...],
) -> str:
    base = f"item:{issue_number}:{context}:{source_view}:{source_page}:{page}"
    return _with_trail(base, trail)


def _action_callback_data(
    action: str,
    issue_number: int,
    context: str,
    page: int,
    source_page: int,
    source_view: str,
    trail: tuple[tuple[int, int], ...],
) -> str:
    if context == "goal" or (context.startswith("g") and context[1:].isdigit()):
        base = (
            f"action:{action}:{issue_number}:{context}:{source_view}:"
            f"{source_page}:{page}"
        )
        return _with_trail(base, trail)
    return f"action:{action}:{issue_number}:{context}:{page}"


def _with_trail(base: str, trail: tuple[tuple[int, int], ...]) -> str:
    if not trail:
        return base
    encoded = ",".join(f"{goal_number}.{page}" for goal_number, page in trail)
    return f"{base}:{encoded}"


def _parse_trail(raw: str) -> tuple[tuple[int, int], ...]:
    if not raw:
        raise ValueError("empty trail")
    result: list[tuple[int, int]] = []
    for entry in raw.split(","):
        goal, separator, page = entry.partition(".")
        if separator != ".":
            raise ValueError("invalid trail")
        goal_number = int(goal)
        page_number = int(page)
        if goal_number <= 0 or page_number < 0:
            raise ValueError("invalid trail")
        result.append((goal_number, page_number))
    return tuple(result)


def _page(items: list[Issue], requested_page: int) -> tuple[list[Issue], int, int]:
    page_count = max(1, (len(items) + PAGE_SIZE - 1) // PAGE_SIZE)
    current_page = min(max(requested_page, 0), page_count - 1)
    start = current_page * PAGE_SIZE
    return items[start : start + PAGE_SIZE], current_page, page_count


def _pagination_row(
    view: str,
    current_page: int,
    page_count: int,
) -> list[InlineKeyboardButton]:
    if page_count <= 1:
        return []

    row: list[InlineKeyboardButton] = []
    if current_page > 0:
        row.append(
            InlineKeyboardButton(text="◀️", callback_data=f"nav:{view}:{current_page - 1}")
        )
    row.append(
        InlineKeyboardButton(
            text=f"{current_page + 1}/{page_count}",
            callback_data="noop",
        )
    )
    if current_page + 1 < page_count:
        row.append(
            InlineKeyboardButton(text="▶️", callback_data=f"nav:{view}:{current_page + 1}")
        )
    return row


def _short_title(title: str, limit: int) -> str:
    normalized = " ".join(title.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "…"


def _status_icon(issue: Issue) -> str:
    if issue.state == "closed":
        return "✅"
    if "state:later" in issue.labels:
        return "🕓"
    if "state:waiting" in issue.labels:
        return "⏳"
    if "state:now" in issue.labels:
        return "🔥"
    if "state:inbox" in issue.labels:
        return "📥"
    return "⬜"


def _is_start(text: str) -> bool:
    first = text.strip().split(maxsplit=1)[0] if text.strip() else ""
    command = first.split("@", maxsplit=1)[0]
    return command == "/start"


def text_link_targets(message: Message) -> tuple[str, ...]:
    entities = message.entities or ()
    return tuple(
        entity.url
        for entity in entities
        if entity.type == "text_link" and entity.url is not None
    )


def describe_forward_origin(message: Message) -> str | None:
    origin = message.forward_origin
    if origin is None:
        return None
    if isinstance(origin, MessageOriginUser):
        username = f"@{origin.sender_user.username}" if origin.sender_user.username else None
        name = origin.sender_user.full_name
        return f"user {username or name} (id={origin.sender_user.id})"
    if isinstance(origin, MessageOriginHiddenUser):
        return f"hidden user {origin.sender_user_name}"
    if isinstance(origin, MessageOriginChat):
        return f"chat {origin.sender_chat.title} (id={origin.sender_chat.id})"
    if isinstance(origin, MessageOriginChannel):
        return (
            f"channel {origin.chat.title} (id={origin.chat.id}), "
            f"message_id={origin.message_id}"
        )
    return "unknown forward origin"
